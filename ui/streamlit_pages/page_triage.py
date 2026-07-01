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
from ...core.lab_analyzer import extract_lab_values, lab_urgency_score
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


def _section_wearable(patient_name: str):
    """
    Sube el JSON, lo importa en la BD de forma incremental,
    y devuelve los registros historicos acumulados para el analisis.
    """
    st.subheader("Datos del wearable")

    with st.expander("Formatos soportados"):
        for name, desc in ADAPTER_NAMES.items():
            st.markdown(f"- **{desc}** (`{name}`)")

    # Selector de dias solo relevante para XML de Apple Health
    col_days, _ = st.columns([2, 3])
    xml_days = col_days.number_input(
        "Dias a importar (solo para XML de Apple Health)",
        min_value=30, max_value=730, value=180, step=30,
        help="Cuantos dias de historial extraer del XML. Para JSON se usan todos los datos.",
    )
    st.session_state["xml_days"] = xml_days

    uploaded = st.file_uploader(
        "Sube el fichero JSON del wearable o el XML de Apple Health",
        type=["json", "xml"],
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
        # Detectar si es XML de Apple Health
        xml_adapter = AppleHealthXMLAdapter()
        if uploaded.name.endswith(".xml") and xml_adapter.can_handle(raw_bytes):
            with st.spinner("Procesando XML de Apple Health... (puede tardar unos minutos)"):
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
                pid = db.get_or_create_patient(patient_name, 0, "")
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


def _section_result(patient, q, w30, w56, rec, spec, reasons,
                    local_bucket, local_score, local_motivos,
                    ai, final_bucket, report) -> None:
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

    tab1, tab2, tab3, tab4 = st.tabs(["Motivos de score", "Justificacion IA", "Analisis clinico", "Informe completo"])
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
        st.divider()
        st.subheader("Analisis clinicos (opcional)")
        st.caption("Sube una foto o imagen de tu analisis de sangre u orina.")
        lab_image = st.file_uploader(
            "Imagen del analisis (JPG, PNG)",
            type=["jpg", "jpeg", "png"],
            key="lab_image_upload",
        )

        submitted = st.form_submit_button(
            "Ejecutar triaje", type="primary", use_container_width=True
        )

    wearable_result = _section_wearable(patient.name)
    records, w30, w56, adapter_name, patient_id = wearable_result

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
                lab_image = st.session_state.get("lab_image_upload")
                if lab_image is not None:
                    with st.spinner("Leyendo analisis clinico con IA..."):
                        mime = "image/jpeg" if lab_image.name.lower().endswith((".jpg",".jpeg")) else "image/png"
                        lab_data = extract_lab_values(lab_image.read(), mime_type=mime)
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
                            st.success(f"Analisis leido correctamente. Valores fuera de rango: {len(lab_data.get('valores_fuera_rango', []))}")
                        else:
                            st.warning(f"No se pudo leer el analisis: {lab_data.get('_error', '')}")

                ai           = get_ai_urgency(pre, patient_name=patient.name)
                # Combinar score local + score de analisis
                combined_score = local_score + lab_score
                if lab_motivos:
                    local_motivos.extend([f"[Lab] {m}" for m in lab_motivos])

                final_bucket = merge_buckets(local_bucket, ai.get("urgency", "2_semanas"))
                # Si el score de lab es muy alto, escalar urgencia
                if combined_score >= 9 and final_bucket != "urgente":
                    final_bucket = "urgente"
                elif combined_score >= 5 and final_bucket == "2_semanas":
                    final_bucket = "7_dias"
                report = build_report(
                    patient, q, w30, w56, rec, spec, reasons,
                    local_bucket, local_score, local_motivos, ai, final_bucket,
                )

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
                )
            except Exception as e:
                st.error(f"Error durante el triaje: {e}")
