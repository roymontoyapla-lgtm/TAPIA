# -*- coding: utf-8 -*-
"""
TAPIA - Streamlit entry point.
Ejecutar con:  streamlit run streamlit_app.py
"""

import sys
import base64
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st
from tapia.core.config import cfg

st.set_page_config(
    page_title=cfg.app.name,
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Inicializar BD y tablas al arrancar
from tapia.db import database as db
from tapia.compliance.audit import init_audit_table
from tapia.compliance.gdpr  import init_consent_table
from tapia.auth.auth        import init_auth_tables, has_permission, ROLES

db.init_db()
init_audit_table()
init_consent_table()
init_auth_tables()

# ---------------------------------------------------------------------------
# Login obligatorio
# ---------------------------------------------------------------------------
from tapia.ui.streamlit_pages.page_login import run as show_login

if not st.session_state.get("authenticated"):
    show_login()
    st.stop()

# ---------------------------------------------------------------------------
# Logo helper
# ---------------------------------------------------------------------------

def _logo_base64() -> str:
    logo_path = Path(__file__).resolve().parent / "Tapia_logo.png"
    if logo_path.exists():
        with open(logo_path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    return ""

_logo_b64 = _logo_base64()

def page_header(title: str) -> None:
    if _logo_b64:
        col1, col2 = st.columns([1, 5])
        with col1:
            st.markdown(
                f'<img src="data:image/png;base64,{_logo_b64}" '
                f'style="width:100%;max-width:140px;margin-top:4px;">',
                unsafe_allow_html=True,
            )
        with col2:
            st.title(title)
    else:
        st.title(title)

st.session_state["page_header"] = page_header

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

from tapia.ui.streamlit_pages import (
    page_triage, page_patients, page_history,
    page_db_history, page_compliance, page_about
)
from tapia.ui.streamlit_pages.page_users import run as page_users_run

role      = st.session_state.get("role", "consultor")
full_name = st.session_state.get("full_name", "Usuario")
role_label= ROLES.get(role, role)

# Paginas disponibles segun rol
all_pages = {
    "Triaje":           (page_triage.run,       "triage"),
    "Pacientes":        (page_patients.run,      "patients"),
    "Historial sesion": (page_history.run,       "history"),
    "Historial BD":     (page_db_history.run,    "db_history"),
    "Cumplimiento":     (page_compliance.run,    "compliance"),
    "Usuarios":         (page_users_run,         "manage_users"),
    "Acerca de":        (page_about.run,         "about"),
}

available = {
    name: fn for name, (fn, perm) in all_pages.items()
    if has_permission(role, perm)
}

with st.sidebar:
    if _logo_b64:
        st.markdown(
            f'<img src="data:image/png;base64,{_logo_b64}" '
            f'style="width:100%;max-width:220px;margin-bottom:8px;">',
            unsafe_allow_html=True,
        )
    else:
        st.markdown("## TAPIA")

    st.caption(f"v{cfg.app.version}")
    st.divider()

    # Info del usuario logueado
    st.markdown(f"**{full_name}**")
    st.caption(f"Rol: {role_label}")
    st.divider()

    selected = st.radio(
        "Navegacion", list(available.keys()),
        label_visibility="collapsed",
    )
    st.divider()

    # Boton de cerrar sesion
    if st.button("Cerrar sesion", use_container_width=True):
        for key in ["authenticated", "user", "username", "role", "full_name"]:
            st.session_state.pop(key, None)
        st.rerun()

    st.caption("Uso orientativo. No sustituye valoracion clinica.")

# ---------------------------------------------------------------------------
# Renderizar pagina seleccionada
# ---------------------------------------------------------------------------

available[selected]()
