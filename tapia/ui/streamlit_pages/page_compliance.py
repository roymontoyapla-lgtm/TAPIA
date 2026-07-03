# -*- coding: utf-8 -*-
"""
Pagina de cumplimiento: auditoria, RGPD y gestion de consentimientos.
"""

from __future__ import annotations

import streamlit as st

from ...compliance.audit import init_audit_table, get_log, get_stats, Action, ALGORITHM_VERSION
from ...compliance.gdpr import (
    init_consent_table, record_consent, get_consent_status,
    has_valid_consent, export_patient_data, erase_patient, data_inventory,
)
from ...db import database as db
from ..session import init


# ---------------------------------------------------------------------------
# Seccion: resumen de auditoria
# ---------------------------------------------------------------------------

def _section_audit() -> None:
    st.subheader("Registro de auditoria")
    stats = get_stats()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total acciones",    stats["total"])
    c2.metric("Version algoritmo", ALGORITHM_VERSION)
    c3.metric("Primera entrada",   stats["first"][:10] if stats["first"] != "N/D" else "N/D")
    c4.metric("Ultima entrada",    stats["last"][:10]  if stats["last"]  != "N/D" else "N/D")

    if stats["by_action"]:
        st.markdown("**Acciones registradas:**")
        for action, count in sorted(stats["by_action"].items()):
            st.markdown(f"- `{action}`: **{count}**")

    st.divider()

    # Filtros
    action_options = ["Todas"] + sorted(stats["by_action"].keys()) if stats["by_action"] else ["Todas"]
    col1, col2 = st.columns([2, 1])
    action_filter = col1.selectbox("Filtrar por accion", action_options)
    limit         = col2.number_input("Mostrar ultimas", min_value=10, max_value=500, value=50, step=10)

    rows = get_log(
        limit=int(limit),
        action_filter=None if action_filter == "Todas" else action_filter,
    )

    if not rows:
        st.info("No hay entradas en el registro de auditoria todavia.")
        return

    st.caption(f"Mostrando {len(rows)} entradas (mas recientes primero)")

    for r in rows:
        details = r.get("details", "") or ""
        bucket  = r.get("final_bucket", "") or ""
        score   = r.get("local_score")
        model   = r.get("ai_model", "") or ""
        pid     = r.get("patient_id")

        summary = f"`{r['timestamp'][:19]}` | `{r['action']}`"
        if pid:    summary += f" | paciente #{pid}"
        if bucket: summary += f" | prioridad: {bucket}"
        if score is not None: summary += f" | score: {score}"
        if model:  summary += f" | modelo: {model}"

        with st.expander(summary):
            st.json({
                "timestamp":         r["timestamp"],
                "accion":            r["action"],
                "patient_id":        pid,
                "version_algoritmo": r["algorithm_version"],
                "prioridad_final":   bucket or None,
                "score_local":       score,
                "modelo_ia":         model or None,
                "detalles":          details or None,
                "fuente":            r.get("source") or None,
            })


# ---------------------------------------------------------------------------
# Seccion: gestion de consentimientos RGPD
# ---------------------------------------------------------------------------

def _section_gdpr() -> None:
    st.subheader("Gestion de consentimiento (RGPD)")

    patients = db.list_patients()
    if not patients:
        st.info("No hay pacientes registrados todavia.")
        return

    patient_options = {p["name"]: p["id"] for p in patients}
    selected_name   = st.selectbox("Selecciona un paciente", list(patient_options.keys()))
    patient_id      = patient_options[selected_name]

    # Estado actual del consentimiento
    status = get_consent_status(patient_id)
    if status:
        granted = bool(status["granted"])
        color   = "#27ae60" if granted else "#c0392b"
        label   = "Consentimiento OTORGADO" if granted else "Consentimiento REVOCADO"
        st.markdown(
            f"<div style='background:{color};color:white;padding:8px 14px;"
            f"border-radius:6px;display:inline-block;'>{label}</div>",
            unsafe_allow_html=True,
        )
        st.caption(f"Ultimo cambio: {status['timestamp'][:19]}")
    else:
        st.warning("No hay registro de consentimiento para este paciente.")

    # Inventario de datos
    inv = data_inventory(patient_id)
    st.markdown("**Datos almacenados (transparencia RGPD art. 13-14):**")
    c1, c2, c3 = st.columns(3)
    c1.metric("Triajes",          inv["triajes"])
    c2.metric("Dias wearable",    inv["dias_wearable"])
    c3.metric("Consentimientos",  inv["consentimientos"])
    st.caption(
        f"Wearable: {inv['wearable_desde']} a {inv['wearable_hasta']} | "
        f"Datos cifrados: {'Si' if inv['datos_cifrados'] else 'No'}"
    )

    st.divider()

    # Acciones RGPD
    tab1, tab2, tab3 = st.tabs(["Consentimiento", "Exportar datos", "Derecho al olvido"])

    with tab1:
        notes = st.text_input("Notas (opcional)", placeholder="Ej. Consentimiento verbal en consulta")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Registrar consentimiento", type="primary"):
                record_consent(patient_id, granted=True, notes=notes)
                st.success("Consentimiento registrado correctamente.")
                st.rerun()
        with c2:
            if st.button("Revocar consentimiento", type="secondary"):
                record_consent(patient_id, granted=False, notes=notes)
                st.warning("Consentimiento revocado y registrado.")
                st.rerun()

    with tab2:
        st.markdown(
            "Exporta todos los datos del paciente en formato JSON "
            "(portabilidad de datos, RGPD art. 20)."
        )
        if st.button("Generar exportacion"):
            json_str = export_patient_data(patient_id, selected_name)
            st.download_button(
                "Descargar datos del paciente (.json)",
                data=json_str.encode("utf-8"),
                file_name=f"tapia_export_{selected_name.replace(' ','_')}.json",
                mime="application/json",
            )
            st.success("Exportacion generada. Haz clic en el boton para descargarla.")

    with tab3:
        st.error(
            "El derecho al olvido (RGPD art. 17) elimina PERMANENTEMENTE todos los datos "
            "del paciente: triajes, historial wearable y consentimientos. "
            "Esta accion no se puede deshacer. Quedara un registro anonimo en la auditoria."
        )
        confirm = st.text_input(
            f"Escribe el nombre completo del paciente para confirmar: {selected_name}",
            key="confirm_erase",
        )
        if st.button("Eliminar todos los datos", type="primary",
                     disabled=(confirm.strip().lower() != selected_name.strip().lower())):
            result = erase_patient(patient_id, selected_name)
            st.success(
                f"Datos eliminados: {result['triajes']} triajes, "
                f"{result['wearable_days']} dias wearable, "
                f"{result['consentimientos']} consentimientos."
            )
            st.rerun()


# ---------------------------------------------------------------------------
# Seccion: documentacion del algoritmo
# ---------------------------------------------------------------------------

def _section_algorithm_doc() -> None:
    st.subheader(f"Documentacion del algoritmo (v{ALGORITHM_VERSION})")
    st.markdown("""
    Este documento describe el algoritmo de triaje de TAPIA para su revision
    clinica o ante comites de evaluacion.

    ---

    **Proposito**

    TAPIA es una herramienta de apoyo a la decision clinica para priorizar
    citas en atencion primaria. Combina datos objetivos de wearable con un
    cuestionario subjetivo del paciente y una validacion mediante IA generativa.
    No realiza diagnosticos ni sustituye la valoracion clinica.

    ---

    **Fuentes de datos**

    - Cuestionario clinico (fiebre, cefalea, estado general, descanso, ejercicio,
      alimentacion, enfermedades preexistentes)
    - Datos de wearable: FC reposo, pasos, minutos de ejercicio, horas de sueno,
      tasa respiratoria y HRV (soporta Fitbit, Garmin, Apple Health, Withings y formato nativo)

    ---

    **Score de urgencia local**

    El algoritmo asigna puntos por cada factor de riesgo:

    | Factor | Puntos |
    |---|---|
    | Edad >= 75 | +3 |
    | Edad 65-74 | +2 |
    | Edad 50-64 | +1 |
    | Fiebre | +3 |
    | Fiebre + mal estado general | +2 (bonus) |
    | Estado general bajo (<=2/5) | +3 |
    | Estado general regular (3/5) | +1 |
    | Descanso insuficiente (<=2/5) | +2 |
    | Descanso regular (3/5) | +1 |
    | Ejercicio muy bajo (<=1 dia) | +2 |
    | Ejercicio bajo (2-3 dias) | +1 |
    | Sueno <6h >= 15 dias/mes | +3 |
    | Sueno <6h 8-14 dias/mes | +2 |
    | Actividad muy baja >= 15 dias/mes | +2 |
    | Actividad muy baja 8-14 dias/mes | +1 |
    | FC reposo >=90 bpm >= 5 dias/mes | +4 |
    | FC reposo >=90 bpm 3-4 dias/mes | +3 |
    | Sueno <6h >= 25 dias en 8 semanas | +1 |

    **Clasificacion por score:**
    - Score >= 9: URGENTE (mismo dia o guardia)
    - Score 5-8: 7 dias
    - Score < 5: 2 semanas

    ---

    **Validacion por IA**

    El informe local se envia anonimizado a un modelo de lenguaje (Claude de Anthropic
    u OpenAI GPT) con instrucciones estrictas de clasificacion. El modelo devuelve
    su propia clasificacion de urgencia y posibles banderas rojas.

    La prioridad final adopta la postura mas conservadora (mas urgente) entre
    la clasificacion local y la de la IA.

    ---

    **Limitaciones conocidas**

    - Los umbrales clinicos son orientativos y no han sido validados en estudios
      clinicos prospectivos.
    - La fiabilidad de los datos de wearable depende del dispositivo y el uso correcto.
    - La IA puede cometer errores; el medico siempre tiene la ultima palabra.
    - El sistema no detecta emergencias vitales (infarto, ictus, etc.);
      ante duda urgente llamar al 112.

    ---

    **Privacidad y seguridad**

    - Nombre del paciente e informe cifrados en reposo (Fernet AES-128)
    - Nombre anonimizado antes de enviarse a la IA externa
    - Registro de auditoria inmutable con version del algoritmo
    - Consentimiento informado registrado por paciente
    - Derecho al olvido implementado (RGPD art. 17)
    """)

    # Descarga del documento
    doc = _generate_algorithm_doc()
    st.download_button(
        "Descargar documentacion del algoritmo (.txt)",
        data=doc.encode("utf-8"),
        file_name=f"tapia_algoritmo_v{ALGORITHM_VERSION}.txt",
        mime="text/plain",
    )


def _generate_algorithm_doc() -> str:
    from datetime import datetime
    lines = [
        f"TAPIA - Documentacion del Algoritmo de Triaje",
        f"Version: {ALGORITHM_VERSION}",
        f"Generado: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "PROPOSITO",
        "Herramienta de apoyo a la decision clinica para priorizar citas en atencion primaria.",
        "No realiza diagnosticos. No sustituye la valoracion clinica del profesional sanitario.",
        "",
        "CLASIFICACION DE URGENCIA",
        "Score >= 9 -> URGENTE",
        "Score 5-8  -> 7 dias",
        "Score < 5  -> 2 semanas",
        "",
        "FACTORES DEL SCORE",
        "Edad >= 75: +3 | 65-74: +2 | 50-64: +1",
        "Fiebre: +3 | Fiebre + mal estado general: +2 (bonus)",
        "Estado general <=2/5: +3 | 3/5: +1",
        "Descanso <=2/5: +2 | 3/5: +1",
        "Ejercicio <=1 dia: +2 | 2-3 dias: +1",
        "Sueno <6h >=15 dias/mes: +3 | 8-14 dias: +2",
        "Actividad muy baja >=15 dias/mes: +2 | 8-14 dias: +1",
        "FC reposo >=90 bpm >=5 dias/mes: +4 | 3-4 dias: +3",
        "Sueno <6h >=25 dias en 8 semanas: +1",
        "",
        "VALIDACION IA",
        "El informe local se envia anonimizado al modelo de lenguaje configurado.",
        "La prioridad final es la mas conservadora entre score local e IA.",
        "",
        "PRIVACIDAD",
        "Datos cifrados en reposo (Fernet AES-128).",
        "Nombre anonimizado antes de enviarse a IA externa.",
        "Auditoria inmutable. Consentimiento por paciente. Derecho al olvido (RGPD art. 17).",
        "",
        "AVISO LEGAL",
        "Informe orientativo. No sustituye valoracion clinica.",
        "Ante emergencia vital llamar al 112.",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entrada principal
# ---------------------------------------------------------------------------

def run() -> None:
    init()
    init_audit_table()
    init_consent_table()

    header = st.session_state.get("page_header")
    if header:
        header("Cumplimiento y auditoria")
    else:
        st.title("Cumplimiento y auditoria")
    st.caption("RGPD, registro de auditoria y documentacion del algoritmo.")

    tab1, tab2, tab3 = st.tabs([
        "Registro de auditoria",
        "RGPD y consentimiento",
        "Documentacion del algoritmo",
    ])
    with tab1:
        _section_audit()
    with tab2:
        _section_gdpr()
    with tab3:
        _section_algorithm_doc()
