# -*- coding: utf-8 -*-
"""
Pagina de informe clinico integral del paciente (solo administradores y medicos).
"""

from __future__ import annotations

import tempfile
import os
from datetime import datetime

import streamlit as st

from ...auth.auth import has_permission
from ...core.patient_report import generate_patient_report, build_patient_context
from ...db.database import (
    list_patients, get_wearable_history,
    get_lab_results, get_by_patient,
)
from ..session import init

try:
    from ...export.pdf import save_pdf, REPORTLAB_OK
except Exception:
    REPORTLAB_OK = False


def run() -> None:
    init()

    header = st.session_state.get("page_header")
    if header:
        header("Informe clinico integral")
    else:
        st.title("Informe clinico integral")

    role = st.session_state.get("role", "consultor")
    if not has_permission(role, "patients"):
        st.error("No tienes permiso para acceder a esta seccion.")
        return

    st.caption(
        "Este informe usa inteligencia artificial para generar una vision global "
        "del estado de salud del paciente. No sustituye la valoracion clinica."
    )

    # ---------------------------------------------------------------------------
    # Seleccion de paciente
    # ---------------------------------------------------------------------------
    patients = list_patients()
    if not patients:
        st.info("No hay pacientes registrados. Ejecuta al menos un triaje primero.")
        return

    patient_options = {
        f"{p['name']} ({p['age']} anos, {p['sex']})": p
        for p in patients
    }
    selected_label = st.selectbox("Selecciona un paciente", list(patient_options.keys()))
    patient = patient_options[selected_label]
    patient_id = patient["id"]

    # ---------------------------------------------------------------------------
    # Resumen de datos disponibles
    # ---------------------------------------------------------------------------
    wearable = get_wearable_history(patient_id)
    labs     = get_lab_results(patient_id)
    triages  = [vars(t) if hasattr(t,'__dict__') else dict(t)
                for t in get_by_patient(patient_id)]

    col1, col2, col3 = st.columns(3)
    col1.metric("Dias de wearable",  len(wearable))
    col2.metric("Analisis clinicos", len(labs))
    col3.metric("Triajes previos",   len(triages))

    if len(wearable) == 0 and len(labs) == 0 and len(triages) == 0:
        st.warning(
            "Este paciente no tiene datos suficientes para generar un informe. "
            "Ejecuta al menos un triaje con datos del wearable."
        )
        return

    # ---------------------------------------------------------------------------
    # Opciones del informe
    # ---------------------------------------------------------------------------
    st.divider()
    with st.expander("Opciones del informe", expanded=False):
        include_wearable = st.checkbox("Incluir datos del wearable", value=True)
        include_labs     = st.checkbox("Incluir analisis clinicos",  value=True)
        include_triages  = st.checkbox("Incluir historial de triajes", value=True)

    # ---------------------------------------------------------------------------
    # Generar informe
    # ---------------------------------------------------------------------------
    st.divider()

    if st.button("Generar informe integral con IA", type="primary", use_container_width=True):
        with st.spinner("Claude esta analizando todos los datos del paciente... (puede tardar 20-30 segundos)"):
            report_text = generate_patient_report(
                patient=patient,
                wearable_records=wearable if include_wearable else [],
                lab_results=labs         if include_labs     else [],
                triage_history=triages   if include_triages  else [],
            )

        st.session_state["last_integral_report"] = report_text
        st.session_state["last_integral_patient"] = patient.get("name", "Paciente")

    # ---------------------------------------------------------------------------
    # Mostrar informe
    # ---------------------------------------------------------------------------
    if "last_integral_report" in st.session_state:
        report_text    = st.session_state["last_integral_report"]
        patient_nombre = st.session_state.get("last_integral_patient", "Paciente")

        st.divider()
        st.subheader("Informe generado")

        if report_text.startswith("Error"):
            st.error(report_text)
        else:
            # Renderizar el markdown del informe
            st.markdown(report_text)

            st.divider()

            # Descargas
            col_txt, col_pdf = st.columns(2)
            fname = f"tapia_informe_integral_{patient_nombre.replace(' ','_')}_{datetime.now().strftime('%Y%m%d_%H%M')}"

            with col_txt:
                st.download_button(
                    "Descargar informe (.txt)",
                    data=report_text.encode("utf-8"),
                    file_name=f"{fname}.txt",
                    mime="text/plain",
                )

            with col_pdf:
                if REPORTLAB_OK:
                    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                        tmp_path = tmp.name
                    try:
                        save_pdf(
                            tmp_path,
                            report_text,
                            patient_name=patient_nombre,
                            patient_age=patient.get("age", 0),
                            patient_sex=patient.get("sex", ""),
                            final_bucket="2_semanas",
                            local_score=0,
                            local_bucket="2_semanas",
                            ai_bucket="2_semanas",
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

            # Contexto enviado a la IA (para transparencia)
            with st.expander("Ver datos enviados a la IA (transparencia)"):
                ctx = build_patient_context(
                    patient,
                    wearable if include_wearable else [],
                    labs     if include_labs     else [],
                    triages  if include_triages  else [],
                )
                st.code(ctx, language=None)
