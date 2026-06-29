# -*- coding: utf-8 -*-
"""
Pagina de gestion de usuarios (solo administradores).
"""

from __future__ import annotations

import streamlit as st

from ...auth.auth import (
    ROLES, create_user, list_users, update_user,
    change_password, delete_user, get_login_attempts,
)
from ..session import init


def run() -> None:
    init()

    header = st.session_state.get("page_header")
    if header:
        header("Gestion de usuarios")
    else:
        st.title("Gestion de usuarios")

    # Solo admins
    if st.session_state.get("role") != "admin":
        st.error("No tienes permiso para acceder a esta seccion.")
        return

    tab1, tab2, tab3 = st.tabs(["Usuarios", "Crear usuario", "Intentos de acceso"])

    # ------------------------------------------------------------------
    # Tab 1: lista de usuarios
    # ------------------------------------------------------------------
    with tab1:
        users = list_users()
        st.caption(f"{len(users)} usuario(s) registrado(s)")

        for u in users:
            role_label = ROLES.get(u["role"], u["role"])
            active_label = "Activo" if u["active"] else "Desactivado"
            color = "#27ae60" if u["active"] else "#c0392b"

            with st.expander(
                f"{u['username']} | {role_label} | "
                f"{u.get('full_name') or ''} | "
                f"Ultimo acceso: {u['last_login'][:10] if u['last_login'] else 'Nunca'}"
            ):
                st.markdown(
                    f"<span style='color:{color};font-weight:bold;'>{active_label}</span>",
                    unsafe_allow_html=True,
                )

                c1, c2 = st.columns(2)
                with c1:
                    new_role = st.selectbox(
                        "Rol", list(ROLES.keys()),
                        index=list(ROLES.keys()).index(u["role"]),
                        key=f"role_{u['id']}",
                    )
                    new_name = st.text_input(
                        "Nombre completo", value=u.get("full_name") or "",
                        key=f"name_{u['id']}",
                    )
                    new_email = st.text_input(
                        "Email", value=u.get("email") or "",
                        key=f"email_{u['id']}",
                    )
                with c2:
                    new_pass = st.text_input(
                        "Nueva contrasena (dejar vacio para no cambiar)",
                        type="password", key=f"pass_{u['id']}",
                    )
                    new_active = st.checkbox(
                        "Usuario activo", value=bool(u["active"]),
                        key=f"active_{u['id']}",
                    )

                col_save, col_del = st.columns([3, 1])
                with col_save:
                    if st.button("Guardar cambios", key=f"save_{u['id']}", type="primary"):
                        update_user(
                            u["id"],
                            role=new_role,
                            full_name=new_name,
                            email=new_email,
                            active=new_active,
                        )
                        if new_pass:
                            change_password(u["id"], new_pass)
                        st.success("Usuario actualizado.")
                        st.rerun()
                with col_del:
                    # No permitir borrar el propio usuario admin
                    own = u["username"] == st.session_state.get("username")
                    if st.button(
                        "Eliminar", key=f"del_{u['id']}", type="secondary",
                        disabled=own,
                    ):
                        delete_user(u["id"])
                        st.success("Usuario eliminado.")
                        st.rerun()

    # ------------------------------------------------------------------
    # Tab 2: crear usuario
    # ------------------------------------------------------------------
    with tab2:
        st.subheader("Nuevo usuario")
        with st.form("create_user_form"):
            c1, c2 = st.columns(2)
            new_username  = c1.text_input("Nombre de usuario *")
            new_password  = c2.text_input("Contrasena *", type="password")
            new_full_name = c1.text_input("Nombre completo")
            new_email_f   = c2.text_input("Email")
            new_role_f    = st.selectbox("Rol *", list(ROLES.keys()),
                                         format_func=lambda r: ROLES[r])
            created = st.form_submit_button("Crear usuario", type="primary")

        if created:
            if not new_username or not new_password:
                st.error("Usuario y contrasena son obligatorios.")
            elif len(new_password) < 6:
                st.error("La contrasena debe tener al menos 6 caracteres.")
            else:
                ok = create_user(
                    new_username, new_password, new_role_f,
                    new_full_name, new_email_f,
                )
                if ok:
                    st.success(f"Usuario '{new_username}' creado con rol {ROLES[new_role_f]}.")
                else:
                    st.error(f"El usuario '{new_username}' ya existe.")

    # ------------------------------------------------------------------
    # Tab 3: intentos de acceso
    # ------------------------------------------------------------------
    with tab3:
        st.subheader("Ultimos intentos de acceso")
        attempts = get_login_attempts(limit=50)
        if not attempts:
            st.info("No hay intentos de acceso registrados.")
        else:
            for a in attempts:
                icon  = "✅" if a["success"] else "❌"
                color = "#27ae60" if a["success"] else "#c0392b"
                st.markdown(
                    f"{icon} `{a['timestamp'][:19]}` — "
                    f"<span style='color:{color};'>{a['username']}</span>",
                    unsafe_allow_html=True,
                )
