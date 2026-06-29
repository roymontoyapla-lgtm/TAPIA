# -*- coding: utf-8 -*-
"""
Pagina de historial persistente (SQLite).
"""

from __future__ import annotations

import streamlit as st

from ...core.triage import URGENCY_LABELS
from ...db import database as db
from ...db.crypto import is_available as crypto_ok, key_path
from ..session import init

_BUCKET_COLOR = {
    "urgente":   "#c0392b",
    "7_dias":    "#e67e22",
    "2_semanas": "#27ae60",
}


def _section_stats() -> None:
    stats = db.get_stats()
    if stats["total"] == 0:
        return
    st.subheader("Estadisticas globales")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total triajes",  stats["total"])
    c2.metric("Urgentes",       stats["urgente"])
    c3.metric("7 dias",         stats["7_dias"])
    c4.metric("2 semanas",      stats["2_semanas"])
    c5.metric("Score medio",    stats["avg_score"])


def _section_list() -> None:
    st.subheader("Triajes guardados")

    query = st.text_input("Buscar por nombre de paciente", placeholder="Escribe parte del nombre...")

    if query.strip():
        rows = db.search_by_name(query.strip())
        st.caption(f"{len(rows)} resultado(s) para '{query}'")
    else:
        rows = db.get_all(limit=200)
        st.caption(f"{len(rows)} triaje(s) en total (maximo 200)")

    if not rows:
        st.info("No hay triajes guardados todavia. Ejecuta uno en la pagina Triaje.")
        return

    filter_bucket = st.selectbox(
        "Filtrar por prioridad",
        ["Todos", "Urgente", "7 dias", "2 semanas"],
        index=0,
    )
    bucket_map = {"Urgente": "urgente", "7 dias": "7_dias", "2 semanas": "2_semanas"}
    if filter_bucket != "Todos":
        rows = [r for r in rows if r.final_bucket == bucket_map[filter_bucket]]

    for row in rows:
        color = _BUCKET_COLOR.get(row.final_bucket, "#555")
        label = URGENCY_LABELS.get(row.final_bucket, row.final_bucket)

        with st.expander(f"#{row.id} | {row.patient_name} | {row.patient_age} anos | {row.created_at} | {label}"):
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Score local",     row.local_score)
            c2.metric("Prioridad local", URGENCY_LABELS.get(row.local_bucket, row.local_bucket))
            c3.metric("Prioridad IA",    URGENCY_LABELS.get(row.ai_bucket, row.ai_bucket))
            c4.metric("Dias wearable",   row.wearable_days)

            st.markdown(f"**AP/Especialista:** {row.rec}" +
                        (f" | Especialidad: {row.spec}" if row.spec and row.spec != "-" else ""))
            if row.ai_model:
                st.caption(f"Modelo IA: {row.ai_model}")

            with st.expander("Ver informe completo"):
                st.code(row.report_text, language=None)

            col_dl, col_del = st.columns([3, 1])
            with col_dl:
                st.download_button(
                    "Descargar informe",
                    data=row.report_text.encode("utf-8"),
                    file_name=f"tapia_{row.patient_name.replace(' ','_')}_{row.created_at[:10]}.txt",
                    mime="text/plain",
                    key=f"dl_db_{row.id}",
                )
            with col_del:
                if st.button("Eliminar", key=f"del_{row.id}", type="secondary"):
                    db.delete_triage(row.id)
                    st.success(f"Triaje #{row.id} eliminado.")
                    st.rerun()


def _section_management() -> None:
    st.subheader("Gestion de datos")

    if crypto_ok():
        st.success(
            f"Cifrado activo (Fernet AES-128).\n\n"
            f"Clave en: {key_path()}\n\n"
            f"Base de datos en: {db.db_path()}"
        )
    else:
        st.warning("Cifrado no disponible. Instala: pip install cryptography")

    st.divider()
    st.markdown("**Zona de peligro**")
    with st.expander("Eliminar todos los registros"):
        st.warning("Esta accion elimina PERMANENTEMENTE todos los triajes. No se puede deshacer.")
        confirm = st.text_input("Escribe BORRAR TODO para confirmar", key="confirm_delete_all")
        if st.button("Eliminar todos", type="primary", disabled=(confirm != "BORRAR TODO")):
            n = db.delete_all()
            st.success(f"{n} registro(s) eliminados.")
            st.rerun()


def run() -> None:
    init()
    db.init_db()
    header = st.session_state.get("page_header")
    if header:
        header("Historial persistente")
    else:
        st.title("Historial persistente")
    st.caption("Todos los triajes se guardan cifrados en una base de datos SQLite local.")
    _section_stats()
    st.divider()
    _section_list()
    st.divider()
    _section_management()
