# -*- coding: utf-8 -*-
"""
Pagina de gestion de pacientes y su historial wearable acumulado.
"""

from __future__ import annotations

import streamlit as st

from ...core.triage import URGENCY_LABELS
from ...core.wearable import filter_by_days, summarize
from ...db import database as db
from ..session import init

_BUCKET_COLOR = {
    "urgente":   "#c0392b",
    "7_dias":    "#e67e22",
    "2_semanas": "#27ae60",
}

try:
    import pandas as pd
    import plotly.graph_objects as go
    CHARTS_OK = True
except ImportError:
    CHARTS_OK = False


def _wearable_charts(patient_id: int) -> None:
    if not CHARTS_OK:
        st.info("Instala plotly y pandas para ver las graficas.")
        return

    records = db.get_wearable_history(patient_id)
    if not records:
        st.info("No hay datos wearable guardados para este paciente.")
        return

    df = pd.DataFrame(records)
    df["fecha"] = pd.to_datetime(df["pulso_reposo_bpm_media"].map(lambda _: None).fillna(df.get("fecha", "")))

    # Reconstruir df correctamente
    rows = []
    for r in records:
        rows.append({
            "fecha":    r.get("fecha"),
            "fc":       r.get("pulso_reposo_bpm_media"),
            "pasos":    r.get("pasos"),
            "sueno":    r.get("sueno_asleep_horas"),
            "ejercicio":r.get("min_ejercicio"),
        })
    df = pd.DataFrame(rows)
    df["fecha"] = pd.to_datetime(df["fecha"])
    for col in ["fc","pasos","sueno","ejercicio"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.sort_values("fecha")

    window = st.selectbox("Ventana temporal", ["Ultimos 30 dias","Ultimas 8 semanas","Todo el historial"])
    if window == "Ultimos 30 dias":
        df = df[df["fecha"] >= df["fecha"].max() - pd.Timedelta(days=30)]
    elif window == "Ultimas 8 semanas":
        df = df[df["fecha"] >= df["fecha"].max() - pd.Timedelta(days=56)]

    st.caption(f"{len(df)} dias | {df['fecha'].min().date()} a {df['fecha'].max().date()}")

    c1, c2 = st.columns(2)
    with c1:
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df["fecha"], y=df["fc"], mode="lines+markers",
                                  line=dict(color="#e74c3c", width=2)))
        fig.add_hline(y=90, line_dash="dot", line_color="#c0392b", annotation_text="Umbral 90 bpm")
        fig.update_layout(title="FC reposo (bpm)", height=280, margin=dict(t=40,b=20), plot_bgcolor="#fafafa")
        st.plotly_chart(fig, use_container_width=True)

        colors = ["#e67e22" if v < 3000 else "#2980b9" for v in df["pasos"].fillna(3000)]
        fig2 = go.Figure()
        fig2.add_bar(x=df["fecha"], y=df["pasos"], marker_color=colors)
        fig2.add_hline(y=3000, line_dash="dot", line_color="#e67e22", annotation_text="3.000 pasos")
        fig2.update_layout(title="Pasos diarios", height=280, margin=dict(t=40,b=20), plot_bgcolor="#fafafa")
        st.plotly_chart(fig2, use_container_width=True)
    with c2:
        colors2 = ["#c0392b" if v < 6 else "#27ae60" for v in df["sueno"].fillna(6)]
        fig3 = go.Figure()
        fig3.add_bar(x=df["fecha"], y=df["sueno"], marker_color=colors2)
        fig3.add_hline(y=6, line_dash="dot", line_color="#e74c3c", annotation_text="Minimo 6h")
        fig3.update_layout(title="Horas de sueno", height=280, margin=dict(t=40,b=20), plot_bgcolor="#fafafa")
        st.plotly_chart(fig3, use_container_width=True)

        fig4 = go.Figure()
        fig4.add_trace(go.Scatter(x=df["fecha"], y=df["ejercicio"], mode="lines+markers",
                                   line=dict(color="#8e44ad", width=2), fill="tozeroy",
                                   fillcolor="rgba(142,68,173,0.1)"))
        fig4.update_layout(title="Minutos de ejercicio", height=280, margin=dict(t=40,b=20), plot_bgcolor="#fafafa")
        st.plotly_chart(fig4, use_container_width=True)


def run() -> None:
    init()
    db.init_db()

    header = st.session_state.get("page_header")
    if header:
        header("Gestion de pacientes")
    else:
        st.title("Gestion de pacientes")
    st.caption("Historial acumulado de wearable y triajes por paciente.")

    patients = db.list_patients()

    if not patients:
        st.info("No hay pacientes registrados todavia. Ejecuta el primer triaje para crear un paciente.")
        return

    st.subheader(f"Pacientes registrados: {len(patients)}")

    for p in patients:
        stats  = db.get_wearable_stats(p["id"])
        triages = db.get_by_patient(p["id"])

        with st.expander(
            f"{p['name']} | {p['age'] or '?'} anos | "
            f"{stats['total_days']} dias wearable | "
            f"{len(triages)} triaje(s)"
        ):
            # Estadisticas wearable
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Dias wearable",    stats["total_days"])
            c2.metric("Primer registro",  stats["first_date"][:10] if stats["first_date"] != "N/D" else "N/D")
            c3.metric("Ultimo registro",  stats["last_date"][:10]  if stats["last_date"]  != "N/D" else "N/D")
            c4.metric("Ultima importacion", stats["last_import"][:10] if stats["last_import"] != "N/D" else "N/D")

            # Ultimos triajes
            if triages:
                st.markdown("**Historial de triajes:**")
                for t in triages[:5]:
                    color = _BUCKET_COLOR.get(t.final_bucket, "#555")
                    label = URGENCY_LABELS.get(t.final_bucket, t.final_bucket)
                    st.markdown(
                        f"- `{t.created_at[:10]}` — "
                        f"<span style='color:{color};font-weight:bold;'>{label}</span> "
                        f"(score: {t.local_score})",
                        unsafe_allow_html=True,
                    )
                    with st.expander(f"Ver informe {t.created_at[:10]}", expanded=False):
                        st.code(t.report_text, language=None)
                        st.download_button(
                            "Descargar informe",
                            data=t.report_text.encode("utf-8"),
                            file_name=f"tapia_{p['name'].replace(' ','_')}_{t.created_at[:10]}.txt",
                            mime="text/plain",
                            key=f"dl_p_{p['id']}_{t.id}",
                        )

            # Graficas del historial wearable
            st.markdown("**Graficas del historial wearable:**")
            _wearable_charts(p["id"])

            # Zona de borrado
            st.divider()
            if st.button(
                f"Eliminar todos los datos de {p['name']}",
                key=f"del_patient_{p['id']}",
                type="secondary",
            ):
                result = db.delete_patient_data(p["id"])
                st.success(
                    f"Eliminados: {result['triages']} triaje(s) y "
                    f"{result['wearable_days']} dias de wearable."
                )
                st.rerun()
