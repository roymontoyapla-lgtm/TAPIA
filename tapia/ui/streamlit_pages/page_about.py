# -*- coding: utf-8 -*-
"""
Pagina Acerca de.
"""

import streamlit as st
from ...core.config import cfg
from ..session import init


def run() -> None:
    init()
    header = st.session_state.get("page_header")
    if header:
        header("Acerca de TAPIA")
    else:
        st.title("Acerca de TAPIA")

    st.markdown(f"""
    **TAPIA** *(Triaje Automatizado Por IA)* es una herramienta orientativa de triaje
    en atencion primaria que combina datos de wearables, un cuestionario clinico
    y un modelo de lenguaje para priorizar citas medicas.

    | | |
    |---|---|
    | **Version** | `{cfg.app.version}` |
    | **Proveedor IA activo** | `{cfg.ai.provider}` |
    | **Modelo OpenAI** | `{", ".join(cfg.ai.openai_models)}` |
    | **Modelo Anthropic** | `{cfg.ai.anthropic_model}` |
    | **Anonimizacion** | `{"Activada" if cfg.ai.anonymize_before_send else "Desactivada"}` |

    ---
    Aviso legal: Este informe es meramente orientativo y no sustituye
    la valoracion clinica de un profesional sanitario.
    """)

    with st.expander("Umbrales clinicos activos (config.yaml)"):
        thr = cfg.thresholds
        urg = cfg.urgency
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown("**Sueno**")
            st.markdown(f"- Horas minimas: `{thr.sleep.low_hours}h`")
            st.markdown(f"- Dias/mes flag AP: `{thr.sleep.low_days_month_ap}`")
            st.markdown(f"- Dias/mes urgente: `{thr.sleep.low_days_month_urgent}`")
        with c2:
            st.markdown("**Actividad**")
            st.markdown(f"- Pasos minimos: `{thr.activity.very_low_steps:,}`")
            st.markdown(f"- Dias/mes AP: `{thr.activity.low_days_month_ap}`")
        with c3:
            st.markdown("**FC reposo**")
            st.markdown(f"- Umbral alto: `>= {thr.hr.high_resting_bpm} bpm`")
            st.markdown(f"- Dias especialista: `{thr.hr.high_days_specialist}`")
        st.divider()
        st.markdown(f"- Score >= `{urg.urgent_threshold}` -> URGENTE")
        st.markdown(f"- Score >= `{urg.week_threshold}` -> 7 dias")
        st.caption("Edita config.yaml para ajustar estos valores.")

    with st.expander("Instalacion y arranque"):
        st.code("""
pip install pyyaml python-dotenv openai anthropic reportlab pillow streamlit plotly pandas cryptography
streamlit run streamlit_app.py
        """, language="bash")

    with st.expander("Formato JSON del wearable"):
        st.code("""
[
  {
    "fecha": "2024-03-01",
    "pulso_reposo_bpm_media": 62,
    "pasos": 7500,
    "min_ejercicio": 35,
    "sueno_asleep_horas": 7.2,
    "respiraciones_por_min_media": 15,
    "hrv_sdnn_ms_media": 42
  }
]
        """, language="json")
