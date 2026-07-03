# -*- coding: utf-8 -*-
"""
Pagina de historial de sesion y graficas del wearable.
"""

from __future__ import annotations
from typing import Any, Dict, List

import streamlit as st

from ...core.config import cfg
from ...core.triage import URGENCY_LABELS
from ...core.wearable import filter_by_days, parse_date
from ..session import clear_history, get_history, get_wearable_records, init

try:
    import pandas as pd
    import plotly.graph_objects as go
    CHARTS_OK = True
except ImportError:
    CHARTS_OK = False

_BUCKET_COLOR = {
    "urgente":   "#c0392b",
    "7_dias":    "#e67e22",
    "2_semanas": "#27ae60",
}


def _section_history() -> None:
    history = get_history()
    st.subheader(f"Historial de triajes ({len(history)} en esta sesion)")

    if not history:
        st.info("Aun no se ha realizado ningun triaje en esta sesion.")
        return

    if st.button("Limpiar historial", type="secondary"):
        clear_history()
        st.rerun()

    for i, rec in enumerate(history):
        color = _BUCKET_COLOR.get(rec.final_bucket, "#555")
        label = URGENCY_LABELS.get(rec.final_bucket, rec.final_bucket)

        with st.expander(
            f"{rec.patient_name} | {rec.patient_age} anos | {rec.timestamp} | {label}",
            expanded=(i == 0),
        ):
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Score local",      rec.local_score)
            c2.metric("Prioridad local",  URGENCY_LABELS.get(rec.local_bucket, rec.local_bucket))
            c3.metric("Prioridad IA",     URGENCY_LABELS.get(rec.ai_bucket, rec.ai_bucket))
            c4.metric("Dias wearable",    rec.wearable_days)

            st.markdown(f"**AP/Especialista:** {rec.rec}" +
                        (f" | Especialidad: {rec.spec}" if rec.spec != "-" else ""))
            st.markdown(f"**Modelo IA:** {rec.ai_model}")

            with st.expander("Ver informe completo"):
                st.code(rec.report_text, language=None)

            st.download_button(
                "Descargar informe",
                data=rec.report_text.encode("utf-8"),
                file_name=f"tapia_{rec.patient_name.replace(' ','_')}_{rec.timestamp.replace(':','').replace(' ','_')}.txt",
                mime="text/plain",
                key=f"dl_{i}",
            )


def _build_dataframe(records: List[Dict[str, Any]]) -> "pd.DataFrame":
    F = cfg.wearable.fields
    rows = []
    for r in records:
        d = parse_date(r.get(cfg.wearable.date_field))
        if d is None:
            continue
        rows.append({
            "fecha":     d.date(),
            "fc":        r.get(F["resting_hr"]),
            "pasos":     r.get(F["steps"]),
            "sueno":     r.get(F["sleep_h"]),
            "ejercicio": r.get(F["exercise_min"]),
            "hrv":       r.get(F["hrv"]),
        })
    df = pd.DataFrame(rows).sort_values("fecha")
    for col in ["fc", "pasos", "sueno", "ejercicio", "hrv"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _section_charts() -> None:
    records = get_wearable_records()
    st.subheader("Graficas del wearable")

    if not records:
        st.info("Las graficas apareceran aqui una vez ejecutes el triaje con un fichero JSON.")
        return

    if not CHARTS_OK:
        st.warning("Instala plotly y pandas para ver las graficas:\npip install plotly pandas")
        return

    df = _build_dataframe(records)
    if df.empty:
        st.warning("No se pudieron extraer datos validos del wearable.")
        return

    thr = cfg.thresholds

    window = st.selectbox(
        "Ventana temporal",
        ["Ultimos 30 dias", "Ultimas 8 semanas", "Todo el historial"],
        index=0,
    )
    if window == "Ultimos 30 dias":
        cutoff = df["fecha"].max() - pd.Timedelta(days=30)
        df = df[df["fecha"] >= cutoff]
    elif window == "Ultimas 8 semanas":
        cutoff = df["fecha"].max() - pd.Timedelta(days=56)
        df = df[df["fecha"] >= cutoff]

    st.caption(f"Mostrando {len(df)} dias | {df['fecha'].min()} a {df['fecha'].max()}")

    col1, col2 = st.columns(2)
    with col1:
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df["fecha"], y=df["fc"], mode="lines+markers",
                                  name="FC reposo (bpm)", line=dict(color="#e74c3c", width=2)))
        fig.add_hline(y=thr.hr.high_resting_bpm, line_dash="dot", line_color="#c0392b",
                      annotation_text=f"Umbral {thr.hr.high_resting_bpm} bpm")
        fig.update_layout(title="Frecuencia cardiaca en reposo", height=300,
                          margin=dict(t=40, b=20), plot_bgcolor="#fafafa")
        st.plotly_chart(fig, use_container_width=True)

        colors_steps = ["#e67e22" if v < thr.activity.very_low_steps else "#2980b9"
                        for v in df["pasos"].fillna(thr.activity.very_low_steps)]
        fig2 = go.Figure()
        fig2.add_bar(x=df["fecha"], y=df["pasos"], marker_color=colors_steps)
        fig2.add_hline(y=thr.activity.very_low_steps, line_dash="dot", line_color="#e67e22",
                       annotation_text=f"{thr.activity.very_low_steps:,} pasos")
        fig2.update_layout(title="Pasos diarios", height=300,
                           margin=dict(t=40, b=20), plot_bgcolor="#fafafa")
        st.plotly_chart(fig2, use_container_width=True)

    with col2:
        colors_sleep = ["#c0392b" if v < thr.sleep.low_hours else "#27ae60"
                        for v in df["sueno"].fillna(thr.sleep.low_hours)]
        fig3 = go.Figure()
        fig3.add_bar(x=df["fecha"], y=df["sueno"], marker_color=colors_sleep)
        fig3.add_hline(y=thr.sleep.low_hours, line_dash="dot", line_color="#e74c3c",
                       annotation_text=f"Minimo {thr.sleep.low_hours}h")
        fig3.update_layout(title="Horas de sueno por noche", height=300,
                           margin=dict(t=40, b=20), plot_bgcolor="#fafafa")
        st.plotly_chart(fig3, use_container_width=True)

        if df["hrv"].notna().any():
            fig4 = go.Figure()
            fig4.add_trace(go.Scatter(x=df["fecha"], y=df["hrv"], mode="lines+markers",
                                      name="HRV (SDNN ms)", line=dict(color="#8e44ad", width=2),
                                      fill="tozeroy", fillcolor="rgba(142,68,173,0.1)"))
            fig4.update_layout(title="HRV - Variabilidad cardiaca", height=300,
                               margin=dict(t=40, b=20), plot_bgcolor="#fafafa")
            st.plotly_chart(fig4, use_container_width=True)
        else:
            st.info("No hay datos de HRV en este fichero.")


def run() -> None:
    init()
    header = st.session_state.get("page_header")
    if header:
        header("Historial y graficas")
    else:
        st.title("Historial y graficas")

    tab1, tab2 = st.tabs(["Historial de triajes", "Graficas del wearable"])
    with tab1:
        _section_history()
    with tab2:
        _section_charts()
