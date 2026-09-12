# -*- coding: utf-8 -*-
"""
Pagina principal de triaje con soporte multi-wearable e historial acumulativo.
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime
from typing import Any, Dict, List, Optional

import streamlit as st

from ...ai.gpt_client import get_ai_urgency
from ...core.config import cfg
from ...core.models import PatientInfo, Questionnaire
from ...core.report import build_report
from ...core.triage import URGENCY_LABELS, merge_buckets, triage_ap_vs_specialist, urgency_score_and_bucket
from ...core.wearable import filter_by_days, summarize
from ...db import database as db
from ...export.pdf import REPORTLAB_OK, save_pdf
from ...wearables.detector import load_and_detect, ADAPTER_NAMES
from ...wearables.cloud import DropboxSource
from ...wearables.sync import sync_patient
from ...core.lab_analyzer import extract_lab_values, lab_urgency_score
from ...core.anthropometry import obesity_urgency_score
from ...core.lifestyle import build_lifestyle_plan, render_plan_text
from ...db.database import save_lab_result, get_latest_lab
from ...wearables.adapter_apple_xml import AppleHealthXMLAdapter
from ...compliance.audit import init_audit_table, log, Action
from ..session import TriageRecord, init, save_triage, set_wearable_records

_BUCKET_COLOR = {
    "urgente":   "#c0392b",
    "7_dias":    "#e67e22",
    "2_semanas": "#27ae60",
}


def _urgency_badge(bucket: str) -> None:
    color = _BUCKET_COLOR.get(bucket, "#555")
    label = URGENCY_LABELS.get(bucket, bucket)
    st.markdown(
        f"""<div style="background:{color};color:white;padding:14px 20px;
        border-radius:10px;font-size:1.2rem;font-weight:bold;
        text-align:center;margin:10px 0;">{label}</div>""",
        unsafe_allow_html=True,
    )


def _section_patient() -> PatientInfo:
    st.subheader("Datos del paciente")
    c1, c2, c3 = st.columns([3, 1, 1])
    name = c1.text_input("Nombre completo", placeholder="Ej. Maria Lopez Garcia")
    age  = c2.number_input("Edad", min_value=1, max_value=129, value=45, step=1)
    sex  = c3.selectbox("Sexo", ["M", "F", "Otro"])
    return PatientInfo(name=name.strip(), age=int(age), sex=sex)


def _section_questionnaire() -> Questionnaire:
    st.subheader("Cuestionario clinico")
    c1, c2 = st.columns(2)
    with c1:
        fever    = st.checkbox("Fiebre actual")
        headache = st.checkbox("Dolor de cabeza en el ultimo mes")
    with c2:
        general = st.slider("Estado general percibido", 1, 5, 3, help="1=muy mal | 5=excelente")
        rest    = st.slider("Calidad del descanso",     1, 5, 3, help="1=muy mal | 5=excelente")
    c3, c4 = st.columns(2)
    with c3:
        exdays = st.number_input("Dias de ejercicio (ultimas semanas)", min_value=0, max_value=60, value=3)
    with c4:
        diet = st.text_input("Estilo de alimentacion", placeholder="mediterranea, vegetariana...")
    chronic = st.text_input(
        "Enfermedades cronicas o preexistentes",
        placeholder="Diabetes, hipertension... (vacio si ninguna)",
    )
    return Questionnaire(
        headache_last_month=headache, fever=fever,
        general_feeling=int(general), diet_style=diet.strip(),
        rested_enough=int(rest), exercise_days_last_weeks=int(exdays),
        other_notes=chronic.strip(),
    )


def _section_anthropometry():
    """
    Peso, altura y circunferencia abdominal (opcional).
    Devuelve dict {weight_kg, height_cm, waist_cm} con None si no se rellena.
    """
    st.subheader("Antropometria (opcional)")
    st.caption("Estos datos permiten calcular el IMC y el riesgo cardiovascular por obesidad abdominal.")
    c1, c2, c3 = st.columns(3)
    with c1:
        weight = st.number_input(
            "Peso (kg)", min_value=0.0, max_value=400.0, value=0.0, step=0.5,
            help="Dejar en 0 si no se quiere indicar.",
        )
    with c2:
        height = st.number_input(
            "Altura (cm)", min_value=0.0, max_value=250.0, value=0.0, step=1.0,
            help="Dejar en 0 si no se quiere indicar.",
        )
    with c3:
        waist = st.number_input(
            "Circunferencia abdominal (cm)", min_value=0.0, max_value=250.0, value=0.0, step=1.0,
            help="Medida a la altura del ombligo. Dejar en 0 si no se quiere indicar.",
        )
    return {
        "weight_kg": weight if weight > 0 else None,
        "height_cm": height if height > 0 else None,
        "waist_cm":  waist  if waist  > 0 else None,
    }


def _section_cloud_sync(patient, patient_id) -> None:
    """
    Carga bajo demanda desde la nube, junto a la subida manual de fichero.

    Apple Health no tiene API: la app del movil (Health Auto Export) deja los
    JSON en una carpeta de Dropbox y aqui se leen cuando hace falta.
    """
    source = DropboxSource(
        folder=cfg.wearable_sync.folder,
        extensions=tuple(cfg.wearable_sync.extensions),
    )

    st.markdown("**O carga los datos guardados en la nube**")

    if not source.is_configured():
        with st.expander("Carga automatica desde Dropbox (sin configurar)"):
            faltan = ", ".join(source.missing_config()) or "las credenciales de Dropbox"
            st.caption(
                f"Falta definir {faltan} en el fichero .env. Con eso, la app "
                "Health Auto Export del iPhone deja los JSON en una carpeta de "
                "Dropbox y TAPIA los carga con un boton, sin subir ficheros a mano."
            )
            st.markdown(
                "1. Crea una app en dropbox.com/developers (acceso *App folder*, "
                "permisos `files.metadata.read` y `files.content.read`).\n"
                "2. Genera un token de refresco y ponlo en `.env`.\n"
                "3. En Health Auto Export, crea una automatizacion que exporte "
                "a esa carpeta en formato JSON con agregacion diaria."
            )
        return

    estado = None
    if patient_id:
        try:
            estado = db.get_sync_state(patient_id, source.NAME)
        except Exception:
            estado = None

    col_btn, col_info = st.columns([2, 3])
    with col_btn:
        pulsado = st.button(
            "Cargar desde Dropbox",
            use_container_width=True,
            disabled=not patient_name,
            help=("Descarga los ficheros nuevos que haya dejado el movil. "
                  "Solo se importan los dias que falten."),
        )
        releer = st.checkbox(
            "Releer todo el historial", value=False,
            help="Vuelve a procesar todos los ficheros, no solo los nuevos.",
        )
    with col_info:
        if not patient_name:
            st.caption("Escribe el nombre del paciente para poder cargar sus datos.")
        elif estado and estado.get("last_sync_at"):
            st.caption(
                f"Ultima sincronizacion: {estado['last_sync_at'][:16].replace('T', ' ')}"
                + (f" | ultimo fichero: {estado['last_file']}" if estado.get("last_file") else "")
            )
        else:
            st.caption("Este paciente no se ha sincronizado todavia con Dropbox.")

    if not pulsado:
        return

    if not patient_name:
        st.warning("Indica primero el nombre del paciente.")
        return

    try:
        pid = patient_id or db.get_or_create_patient(patient_name, patient.age, patient.sex)
    except Exception as e:
        st.error(f"No se pudo identificar al paciente: {e}")
        return

    with st.spinner("Descargando datos desde Dropbox..."):
        resultado = sync_patient(
            pid, source=source, full=releer, max_files=cfg.wearable_sync.max_files,
        )

    for error in resultado.errors:
        st.warning(error)

    if resultado.days_inserted:
        st.success(resultado.summary())
        log(
            Action.WEARABLE_IMPORT,
            patient_id=pid,
            source=source.NAME,
            details=(f"ficheros={resultado.files_imported};"
                     f"dias_nuevos={resultado.days_inserted};"
                     f"formatos={','.join(resultado.adapters) or 'N/D'}"),
        )
        st.rerun()
    elif not resultado.errors:
        st.info(resultado.summary())


def _section_wearable(patient):
    """
    Sube el JSON, lo importa en la BD de forma incremental,
    y devuelve los registros historicos acumulados para el analisis.
    `patient` es un PatientInfo con name, age y sex ya rellenados en el formulario.
    """
    patient_name = patient.name
    st.subheader("Datos del wearable")

    with st.expander("Formatos soportados"):
        for name, desc in ADAPTER_NAMES.items():
            st.markdown(f"- **{desc}** (`{name}`)")

    # Selector de dias solo relevante para XML/ZIP de Apple Health
    col_days, _ = st.columns([2, 3])
    xml_days = col_days.number_input(
        "Dias a importar (solo para Apple Health)",
        min_value=30, max_value=730, value=180, step=30,
        help="Cuantos dias de historial extraer. Para JSON se usan todos los datos.",
    )
    st.session_state["xml_days"] = xml_days

    st.info(
        "💡 **Consejo de velocidad:** si usas Apple Health, sube directamente el "
        "**ZIP** que exporta el iPhone sin descomprimirlo. Es hasta 10 veces mas "
        "rapido de subir que el XML suelto y TAPIA lo lee igual de bien."
    )

    uploaded = st.file_uploader(
        "Sube el fichero JSON, el ZIP o el XML de Apple Health",
        type=["json", "xml", "zip"],
        help="TAPIA guarda los datos de forma acumulativa. Solo se importan los dias nuevos.",
    )

    # Si hay paciente con historial previo, mostrarlo
    patient_id = None
    if patient_name:
        try:
            # Buscar si ya existe el paciente en BD
            patients = db.list_patients()
            for p in patients:
                if p["name"].lower() == patient_name.lower():
                    patient_id = p["id"]
                    break

            if patient_id:
                stats = db.get_wearable_stats(patient_id)
                if stats["total_days"] > 0:
                    st.info(
                        f"Historial existente: **{stats['total_days']} dias** "
                        f"({stats['first_date']} a {stats['last_date']}) | "
                        f"Ultima importacion: {stats['last_import'][:10]}"
                    )
        except Exception:
            pass

    _section_cloud_sync(patient, patient_id)

    if uploaded is None:
        # Si no sube fichero pero hay historial, usar el historial
        if patient_id:
            history = db.get_wearable_history(patient_id)
            if history:
                set_wearable_records(history)
                w30 = summarize(filter_by_days(history, cfg.wearable.window_short))
                w56 = summarize(filter_by_days(history, cfg.wearable.window_long))
                st.caption(f"Usando historial guardado: {len(history)} dias totales")
                with st.expander("Vista previa wearable (ultimo mes)", expanded=True):
                    _preview_wearable(w30)
                return history, w30, w56, None, patient_id
        return None, None, None, None, patient_id

    try:
        raw_bytes = uploaded.read()
        # Detectar si es XML o ZIP de Apple Health
        xml_adapter  = AppleHealthXMLAdapter()
        is_apple_hf  = uploaded.name.lower().endswith((".xml", ".zip")) and xml_adapter.can_handle(raw_bytes)

        if is_apple_hf:
            origen = "ZIP" if raw_bytes[:2] == b"PK" else "XML"
            with st.spinner(f"Procesando {origen} de Apple Health... (puede tardar unos minutos)"):
                days_xml = st.session_state.get("xml_days", 180)
                records_norm = xml_adapter.normalize(raw_bytes, days=days_xml)
            from ...wearables.detector import to_tapia_dicts
            new_records  = to_tapia_dicts(records_norm)
            adapter_name = xml_adapter.NAME
        else:
            new_records, adapter_name = load_and_detect(raw_bytes)

        if not new_records:
            st.error("El fichero no contiene registros validos.")
            return None, None, None, None, patient_id

        # Importacion incremental en BD
        if patient_name:
            try:
                pid = db.get_or_create_patient(patient_name, patient.age, patient.sex)
                result = db.import_wearable_records(pid, new_records, source=adapter_name)
                patient_id = pid

                if result["inserted"] > 0 and result["skipped"] > 0:
                    st.success(
                        f"Formato: **{ADAPTER_NAMES.get(adapter_name, adapter_name)}** | "
                        f"Nuevos dias importados: **{result['inserted']}** | "
                        f"Ya existian: **{result['skipped']}**"
                    )
                elif result["inserted"] > 0:
                    st.success(
                        f"Formato: **{ADAPTER_NAMES.get(adapter_name, adapter_name)}** | "
                        f"**{result['inserted']}** dias importados correctamente"
                    )
                else:
                    st.info("Todos los dias de este fichero ya estaban guardados. No hay datos nuevos.")

            except Exception as e:
                st.warning(f"No se pudo guardar en BD: {e}. Se usa solo el fichero subido.")
                patient_id = None

        # Combinar fichero nuevo con historial existente para el analisis
        if patient_id:
            all_records = db.get_wearable_history(patient_id)
        else:
            all_records = new_records

        set_wearable_records(all_records)
        w30 = summarize(filter_by_days(all_records, cfg.wearable.window_short))
        w56 = summarize(filter_by_days(all_records, cfg.wearable.window_long))

        with st.expander("Vista previa wearable (ultimo mes)", expanded=True):
            _preview_wearable(w30)

        return all_records, w30, w56, adapter_name, patient_id

    except ValueError as e:
        st.error(str(e))
        return None, None, None, None, patient_id
    except Exception as e:
        st.error(f"Error al leer el fichero: {e}")
        return None, None, None, None, patient_id


def _preview_wearable(w) -> None:
    def _v(val, unit=""): return f"{val}{unit}" if val is not None else "N/D"
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("FC reposo media",  _v(w.avg_resting_hr, " bpm"))
    c2.metric("Pasos medios/dia", _v(w.avg_steps))
    c3.metric("Sueno medio",      _v(w.avg_sleep_h, " h"))
    c4.metric("Ejercicio medio",  _v(w.avg_exercise_min, " min"))
    st.caption(
        f"{w.days} dias | {w.range} | "
        f"Sueno <6h: {w.low_sleep_days} | "
        f"<3000 pasos: {w.very_low_activity_days} | "
        f"FC >=90: {w.high_resting_hr_days}"
    )


def _lifestyle_tab(plan) -> None:
    """Resumen del plan de alimentacion y ejercicio dentro del triaje."""
    if plan is None:
        st.info("No se ha podido calcular el plan con los datos disponibles.")
        return

    n, e = plan.nutrition, plan.exercise
    en   = n.energy

    if plan.medical_clearance:
        st.error(
            "Requiere autorizacion medica antes de iniciar el programa de ejercicio. "
            "Hasta entonces, solo actividad ligera."
        )

    c1, c2, c3 = st.columns(3)
    c1.metric("Ingesta objetivo",
              f"{en.target_kcal} kcal/dia" if en.target_kcal else "N/D",
              en.objective_label, delta_color="off")
    c2.metric("Ejercicio objetivo", f"{e.weekly_min_target} min/sem",
              f"inicio: {e.weekly_min_start} min/sem", delta_color="off")
    c3.metric("Pasos objetivo", f"{e.steps_goal}/dia",
              f"actual: {e.baseline_steps}" if e.baseline_steps is not None else "sin wearable",
              delta_color="off")

    cA, cB = st.columns(2)
    with cA:
        st.markdown("**Alimentacion**")
        st.caption(n.pattern)
        for p in n.priorities[:4]:
            st.markdown(f"- {p}")
    with cB:
        st.markdown("**Ejercicio**")
        st.caption(f"Intensidad: {e.intensity}")
        for p in e.progression[:4]:
            st.markdown(f"- {p}")

    if plan.cautions:
        st.markdown("**Avisos de seguridad**")
        for c in plan.cautions:
            st.warning(c)

    st.markdown("**Objetivos**")
    for g in plan.goals[:6]:
        st.markdown(f"- {g}")

    st.caption(
        "Plan orientativo segun las directrices de la OMS. "
        "En la pagina 'Plan de salud' puede ampliarse, redactarse con IA y descargarse."
    )
    with st.expander("Ver el plan completo"):
        st.code(render_plan_text(plan), language=None)


def _section_result(patient, q, w30, w56, rec, spec, reasons,
                    local_bucket, local_score, local_motivos,
                    ai, final_bucket, report,
                    lab_data=None, lab_score=0,
                    anthro_data=None, obesity_score=0,
                    lifestyle_plan=None) -> None:
    st.divider()
    st.subheader("Resultado del triaje")
    _urgency_badge(final_bucket)

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("**AP vs Especialista**")
        st.info(f"**{rec}**")
        if spec != "-":
            st.warning(f"Especialidad sugerida: {spec}")
    with c2:
        st.markdown("**Prioridad IA**")
        ai_bucket = ai.get("urgency", "2_semanas")
        col   = _BUCKET_COLOR.get(ai_bucket, "#555")
        label = URGENCY_LABELS.get(ai_bucket, ai_bucket)
        st.markdown(f"<span style='color:{col};font-weight:bold;'>{label}</span>",
                    unsafe_allow_html=True)
        if ai.get("_model_used"):
            st.caption(f"Modelo: {ai['_model_used']}")
    with c3:
        st.markdown("**Score local**")
        st.metric("Puntuacion", local_score,
                  delta=URGENCY_LABELS[local_bucket], delta_color="off")

    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "Motivos de score", "Justificacion IA", "Analisis clinico",
        "Antropometria", "Plan de salud", "Informe completo",
    ])
    with tab1:
        st.markdown("**Factores del score:**")
        for m in local_motivos: st.markdown(f"- {m}")
        st.markdown("**Motivos AP vs especialista:**")
        for r in reasons[:6]: st.markdown(f"- {r}")
    with tab2:
        if ai.get("justification"):
            st.markdown(ai["justification"])
        if ai.get("red_flags"):
            st.error("**Banderas rojas detectadas:**")
            for rf in ai["red_flags"]: st.markdown(f"- {rf}")
        if not ai.get("justification") and not ai.get("red_flags"):
            st.info("La IA no genero justificacion adicional.")
    with tab3:
        if lab_data and lab_data.get("_success"):
            col1, col2, col3 = st.columns(3)
            with col1:
                st.markdown("**Hemograma**")
                hema = lab_data.get("hemograma", {})
                for k, v in hema.items():
                    if v is not None:
                        st.markdown(f"- {k.replace('_',' ')}: **{v}**")
            with col2:
                st.markdown("**Bioquimica**")
                bio = lab_data.get("bioquimica", {})
                for k, v in bio.items():
                    if v is not None:
                        st.markdown(f"- {k.replace('_',' ')}: **{v}**")
            with col3:
                st.markdown("**Orina**")
                ori = lab_data.get("orina", {})
                for k, v in ori.items():
                    if v is not None:
                        st.markdown(f"- {k.replace('_',' ')}: **{v}**")
            if lab_data.get("valores_fuera_rango"):
                st.error("**Valores fuera de rango:**")
                for v in lab_data["valores_fuera_rango"]:
                    st.markdown(f"- {v}")
            if lab_score > 0:
                st.warning(f"Score adicional por analisis: **+{lab_score}**")
        else:
            st.info("No se subio ningun analisis clinico en este triaje.")

    with tab4:
        if anthro_data and (anthro_data.get("weight_kg") or anthro_data.get("height_cm") or anthro_data.get("waist_cm")):
            c1, c2, c3 = st.columns(3)
            c1.metric("Peso",   f"{anthro_data.get('weight_kg') or 'N/D'} kg")
            c2.metric("Altura", f"{anthro_data.get('height_cm') or 'N/D'} cm")
            c3.metric("Circunf. abdominal", f"{anthro_data.get('waist_cm') or 'N/D'} cm")

            c4, c5 = st.columns(2)
            with c4:
                st.markdown("**IMC (Indice de Masa Corporal)**")
                bmi = anthro_data.get("bmi")
                bmi_cat = anthro_data.get("bmi_category", "N/D")
                if bmi is not None:
                    st.metric("IMC", bmi, delta=bmi_cat, delta_color="off")
                else:
                    st.info("Introduce peso y altura para calcular el IMC.")
            with c5:
                st.markdown("**Riesgo cardiovascular (circunf. abdominal)**")
                waist_cat = anthro_data.get("waist_category", "N/D")
                if anthro_data.get("waist_cm") is not None:
                    color = "#c0392b" if "muy" in waist_cat else ("#e67e22" if "aumentado" in waist_cat else "#27ae60")
                    st.markdown(f"<span style='color:{color};font-weight:bold;'>{waist_cat}</span>",
                               unsafe_allow_html=True)
                else:
                    st.info("Introduce la circunferencia abdominal para calcular el riesgo.")

            if obesity_score > 0:
                st.warning(f"Score adicional por antropometria: **+{obesity_score}**")
        else:
            st.info("No se introdujeron datos antropometricos en este triaje.")

    with tab5:
        _lifestyle_tab(lifestyle_plan)

    with tab6:
        st.code(report, language=None)

    st.divider()
    _download_buttons(report, patient, final_bucket, local_score, local_bucket,
                      ai.get("urgency","2_semanas"), ai.get("justification",""),
                      ai.get("red_flags",[]), w30, reasons, local_motivos)


def _download_buttons(report, patient, final_bucket, local_score, local_bucket,
                      ai_bucket, ai_just, ai_flags, w30, reasons, motivos) -> None:
    c1, c2 = st.columns(2)
    fname = f"tapia_{patient.name.replace(' ','_')}_{datetime.now().strftime('%Y%m%d_%H%M')}"
    with c1:
        st.download_button(
            "Descargar informe (.txt)",
            data=report.encode("utf-8"),
            file_name=f"{fname}.txt",
            mime="text/plain",
        )
    with c2:
        if REPORTLAB_OK:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp_path = tmp.name
            try:
                w30_data = {
                    "avg_resting_hr":         w30.avg_resting_hr,
                    "avg_steps":              w30.avg_steps,
                    "avg_sleep_h":            w30.avg_sleep_h,
                    "avg_exercise_min":       w30.avg_exercise_min,
                    "low_sleep_days":         w30.low_sleep_days,
                    "very_low_activity_days": w30.very_low_activity_days,
                    "high_resting_hr_days":   w30.high_resting_hr_days,
                }
                save_pdf(
                    tmp_path, report,
                    patient_name=patient.name, patient_age=patient.age, patient_sex=patient.sex,
                    final_bucket=final_bucket, local_score=local_score, local_bucket=local_bucket,
                    ai_bucket=ai_bucket, ai_justification=ai_just, ai_red_flags=ai_flags,
                    w30_data=w30_data, reasons=reasons, local_motivos=motivos,
                )
                with open(tmp_path, "rb") as f:
                    pdf_bytes = f.read()
                st.download_button(
                    "Descargar informe (.pdf)",
                    data=pdf_bytes,
                    file_name=f"{fname}.pdf",
                    mime="application/pdf",
                )
            except Exception as e:
                st.warning(f"No se pudo generar el PDF: {e}")
            finally:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
        else:
            st.info("Instala reportlab para habilitar la descarga en PDF.")


def run() -> None:
    init()
    db.init_db()

    header = st.session_state.get("page_header")
    if header:
        header("Triaje de paciente")
    else:
        st.title("Triaje de paciente")
    st.caption(
        "Sube el JSON del wearable (ultimos 6 meses). "
        "TAPIA acumula los datos automaticamente y evita duplicados."
    )

    with st.form("triage_form"):
        patient = _section_patient()
        st.divider()
        q = _section_questionnaire()
        st.divider()
        anthro_input = _section_anthropometry()
        st.divider()
        st.divider()
        st.subheader("Analisis clinicos (opcional)")
        st.caption(
            "Sube una o varias fotos de tu analisis de sangre u orina "
            "(por ejemplo, si el informe tiene varias paginas, sube cada pagina en orden)."
        )
        lab_images = st.file_uploader(
            "Imagenes del analisis (JPG, PNG) - puedes seleccionar varias",
            type=["jpg", "jpeg", "png"],
            key="lab_image_upload",
            accept_multiple_files=True,
        )
        if lab_images:
            st.caption(f"{len(lab_images)} pagina(s) seleccionada(s): " +
                      ", ".join(f.name for f in lab_images))

        submitted = st.form_submit_button(
            "Ejecutar triaje", type="primary", use_container_width=True
        )

    wearable_result = _section_wearable(patient)
    records, w30, w56, adapter_name, patient_id = wearable_result

    # Sincroniza edad/sexo del paciente en BD con lo indicado en el formulario
    # (autorrepara registros antiguos que se guardaron sin estos datos)
    if patient_id:
        db.update_patient_info(patient_id, patient.age, patient.sex)

    if submitted:
        if not patient.name:
            st.error("El nombre del paciente no puede estar vacio.")
            return
        if records is None or w30 is None:
            st.error("No hay datos del wearable disponibles. Sube un fichero JSON o asegurate de que el paciente tiene historial guardado.")
            return

        with st.spinner("Ejecutando triaje y consultando IA..."):
            try:
                rec, spec, reasons = triage_ap_vs_specialist(q, w30, w56)
                local_bucket, local_score, local_motivos = urgency_score_and_bucket(patient, q, w30, w56)
                pre = build_report(
                    patient, q, w30, w56, rec, spec, reasons,
                    local_bucket, local_score, local_motivos,
                    {"urgency": "2_semanas", "justification": "", "red_flags": []}, local_bucket,
                )
                # Procesar analisis clinico si se subio imagen
                lab_data  = {}
                lab_score = 0
                lab_motivos = []
                lab_images_uploaded = st.session_state.get("lab_image_upload")
                if lab_images_uploaded:
                    n_pages = len(lab_images_uploaded)
                    spinner_msg = (
                        f"Leyendo analisis clinico con IA ({n_pages} pagina{'s' if n_pages>1 else ''})..."
                    )
                    with st.spinner(spinner_msg):
                        images_payload = []
                        for f in lab_images_uploaded:
                            mime = "image/jpeg" if f.name.lower().endswith((".jpg",".jpeg")) else "image/png"
                            images_payload.append((f.read(), mime))
                        lab_data = extract_lab_values(images_payload)
                        if lab_data.get("_success"):
                            lab_score, lab_motivos = lab_urgency_score(lab_data)
                            if patient_id:
                                import json as _json
                                save_lab_result(
                                    patient_id=patient_id,
                                    raw_json=_json.dumps(lab_data, ensure_ascii=False),
                                    fecha=lab_data.get("fecha_analisis"),
                                    laboratorio=lab_data.get("laboratorio"),
                                    score_lab=lab_score,
                                )
                            pages_done = lab_data.get("_pages_processed", n_pages)
                            st.success(
                                f"Analisis leido correctamente ({pages_done} pagina{'s' if pages_done>1 else ''}). "
                                f"Valores fuera de rango: {len(lab_data.get('valores_fuera_rango', []))}"
                            )
                        else:
                            st.warning(f"No se pudo leer el analisis: {lab_data.get('_error', '')}")

                # Calcular riesgo de obesidad (peso/altura/circunf. abdominal)
                obesity_score, obesity_motivos, bmi, bmi_cat, waist_cat = obesity_urgency_score(
                    anthro_input.get("weight_kg"),
                    anthro_input.get("height_cm"),
                    anthro_input.get("waist_cm"),
                    patient.sex,
                )
                anthro_data = {
                    **anthro_input,
                    "bmi": bmi,
                    "bmi_category": bmi_cat,
                    "waist_category": waist_cat,
                }
                if obesity_motivos:
                    local_motivos.extend([f"[Antropometria] {m}" for m in obesity_motivos])

                ai           = get_ai_urgency(pre, patient_name=patient.name)
                # Combinar score local + score de analisis + score de obesidad
                combined_score = local_score + lab_score + obesity_score
                if lab_motivos:
                    local_motivos.extend([f"[Lab] {m}" for m in lab_motivos])

                final_bucket = merge_buckets(local_bucket, ai.get("urgency", "2_semanas"))
                # Si el score combinado es muy alto, escalar urgencia
                if combined_score >= 9 and final_bucket != "urgente":
                    final_bucket = "urgente"
                elif combined_score >= 5 and final_bucket == "2_semanas":
                    final_bucket = "7_dias"
                report = build_report(
                    patient, q, w30, w56, rec, spec, reasons,
                    local_bucket, local_score, local_motivos, ai, final_bucket,
                    anthro=anthro_data,
                )

                # Guardar la antropometria en el historico del paciente
                if patient_id:
                    db.save_anthropometry(
                        patient_id=patient_id,
                        weight_kg=anthro_data.get("weight_kg"),
                        height_cm=anthro_data.get("height_cm"),
                        waist_cm=anthro_data.get("waist_cm"),
                        bmi=anthro_data.get("bmi"),
                        bmi_category=anthro_data.get("bmi_category", ""),
                        waist_category=anthro_data.get("waist_category", ""),
                    )

                # Plan de alimentacion y ejercicio (calculo deterministico)
                try:
                    lifestyle_plan = build_lifestyle_plan(
                        patient=patient, q=q, anthro=anthro_data, w30=w30,
                        lab_data=lab_data or None, final_bucket=final_bucket,
                    )
                    # Solo se archiva el plan si hay antropometria: sin peso ni
                    # altura el plan es generico y no aporta historico.
                    has_anthro = any(
                        anthro_data.get(k) for k in ("weight_kg", "height_cm", "waist_cm")
                    )
                    if patient_id and has_anthro:
                        db.save_lifestyle_plan(
                            patient_id=patient_id,
                            plan_text=render_plan_text(lifestyle_plan),
                            objective=lifestyle_plan.nutrition.energy.objective,
                            target_kcal=lifestyle_plan.nutrition.energy.target_kcal,
                            weekly_min=lifestyle_plan.exercise.weekly_min_target,
                            steps_goal=lifestyle_plan.exercise.steps_goal,
                            clearance=lifestyle_plan.medical_clearance,
                        )
                except Exception as e:
                    lifestyle_plan = None
                    st.warning(f"No se pudo calcular el plan de alimentacion y ejercicio: {e}")

                save_triage(TriageRecord(
                    timestamp=datetime.now().strftime("%Y-%m-%d %H:%M"),
                    patient_name=patient.name, patient_age=patient.age, patient_sex=patient.sex,
                    local_bucket=local_bucket, local_score=local_score, final_bucket=final_bucket,
                    ai_bucket=ai.get("urgency","2_semanas"), ai_model=ai.get("_model_used","N/D"),
                    rec=rec, spec=spec, report_text=report, wearable_days=w30.days,
                ))
                db.save_triage(
                    patient_name=patient.name, patient_age=patient.age, patient_sex=patient.sex,
                    local_bucket=local_bucket, local_score=local_score, final_bucket=final_bucket,
                    ai_bucket=ai.get("urgency","2_semanas"), ai_model=ai.get("_model_used",""),
                    rec=rec, spec=spec, wearable_days=w30.days, report_text=report,
                    patient_id=patient_id,
                )
                # Registrar en auditoria
                log(
                    Action.TRIAGE_RUN,
                    patient_id=patient_id,
                    final_bucket=final_bucket,
                    local_score=local_score,
                    ai_model=ai.get("_model_used",""),
                    details=f"dias_wearable={w30.days}",
                )

                _section_result(
                    patient, q, w30, w56, rec, spec, reasons,
                    local_bucket, local_score, local_motivos, ai, final_bucket, report,
                    lab_data=lab_data, lab_score=lab_score,
                    anthro_data=anthro_data, obesity_score=obesity_score,
                    lifestyle_plan=lifestyle_plan,
                )
            except Exception as e:
                st.error(f"Error durante el triaje: {e}")
