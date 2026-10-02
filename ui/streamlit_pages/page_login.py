# -*- coding: utf-8 -*-
"""
Pantalla de login de TAPIA.
"""

from __future__ import annotations

import base64
from pathlib import Path

import streamlit as st

from ...auth.auth import login, init_auth_tables


def _logo_html() -> str:
    raiz = Path(__file__).resolve().parent.parent.parent
    logo_path = raiz / "Tapia_logo_transparente.png"
    if not logo_path.exists():
        logo_path = raiz / "Tapia_logo.png"
    if logo_path.exists():
        with open(logo_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        return f'<img src="data:image/png;base64,{b64}" style="width:220px;margin-bottom:8px;">'
    return "<h1>TAPIA</h1>"


def run() -> bool:
    """
    Muestra la pantalla de login.
    Devuelve True si el usuario se ha autenticado correctamente.
    """
    init_auth_tables()

    # Si ya hay sesion activa, no mostrar login
    if st.session_state.get("authenticated"):
        return True

    # Centrar el formulario
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown(
            f'<div style="text-align:center;padding:48px 0 8px;">{_logo_html()}</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            '<p style="text-align:center;color:#6e6e73;font-size:1.05rem;'
            'letter-spacing:-.01em;margin-bottom:28px;">'
            'Triaje Automatizado por medio de la Inteligencia Artificial</p>',
            unsafe_allow_html=True,
        )

        with st.form("login_form"):
            st.subheader("Iniciar sesion")
            username = st.text_input("Usuario", placeholder="tu_usuario")
            password = st.text_input("Contrasena", type="password", placeholder="••••••••")
            submitted = st.form_submit_button(
                "Entrar", type="primary", use_container_width=True
            )

        if submitted:
            if not username or not password:
                st.error("Introduce usuario y contrasena.")
                return False

            user = login(username, password)
            if user:
                st.session_state["authenticated"] = True
                st.session_state["user"]          = user
                st.session_state["username"]      = user["username"]
                st.session_state["role"]          = user["role"]
                st.session_state["full_name"]     = user.get("full_name") or user["username"]
                st.rerun()
            else:
                st.error("Usuario o contrasena incorrectos.")
                return False

        st.divider()
        st.caption(
            "Primera vez? La clave del usuario **admin** se genera al crear la base "
            "de datos y se muestra en la consola de arranque."
        )

    return False
