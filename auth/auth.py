# -*- coding: utf-8 -*-
"""
Sistema de autenticacion y roles para TAPIA.

Roles disponibles:
  - admin     : acceso total, gestion de usuarios
  - medico    : acceso a triaje, pacientes, historial
  - consultor : solo lectura (historial y graficas)

Las contrasenas se almacenan como hash SHA-256 + salt.
"""

from __future__ import annotations

import hashlib
import logging
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

logger = logging.getLogger(__name__)

_DB_PATH = Path(__file__).resolve().parent.parent / "tapia_history.db"

ROLES = {
    "admin":     "Administrador",
    "medico":    "Medico",
    "consultor": "Consultor (solo lectura)",
}

# Permisos por rol
PERMISSIONS = {
    "admin": {
        "triage", "patients", "history", "db_history",
        "compliance", "about", "manage_users",
    },
    "medico": {
        "triage", "patients", "history", "db_history",
        "compliance", "about",
    },
    "consultor": {
        "history", "db_history", "about",
    },
}


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Esquema
# ---------------------------------------------------------------------------

def init_auth_tables() -> None:
    """Crea las tablas de usuarios y sesiones. Idempotente."""
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                username     TEXT    NOT NULL UNIQUE,
                password_hash TEXT   NOT NULL,
                salt         TEXT    NOT NULL,
                role         TEXT    NOT NULL DEFAULT 'medico',
                full_name    TEXT,
                email        TEXT,
                active       INTEGER NOT NULL DEFAULT 1,
                created_at   TEXT    NOT NULL,
                last_login   TEXT
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)"
        )
        conn.execute("""
            CREATE TABLE IF NOT EXISTS login_attempts (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                username   TEXT NOT NULL,
                success    INTEGER NOT NULL,
                timestamp  TEXT NOT NULL,
                ip_hint    TEXT
            )
        """)

    # Crear usuario admin por defecto si no existe ninguno
    _ensure_default_admin()
    logger.debug("Tablas de autenticacion inicializadas.")


def _ensure_default_admin() -> None:
    """Crea el usuario admin por defecto si la tabla esta vacia."""
    with _connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if count == 0:
            _create_user_internal(conn, "admin", "tapia1234", "admin", "Administrador")
            logger.info("Usuario admin por defecto creado (usuario: admin, clave: tapia1234)")


def _create_user_internal(
    conn: sqlite3.Connection,
    username: str,
    password: str,
    role: str,
    full_name: str = "",
    email: str = "",
) -> None:
    salt = secrets.token_hex(32)
    pwd_hash = _hash_password(password, salt)
    now = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        """INSERT INTO users
           (username, password_hash, salt, role, full_name, email, active, created_at)
           VALUES (?,?,?,?,?,?,1,?)""",
        (username.lower().strip(), pwd_hash, salt, role, full_name, email, now),
    )


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------

def _hash_password(password: str, salt: str) -> str:
    combined = f"{salt}{password}{salt}"
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()


def _verify_password(password: str, salt: str, stored_hash: str) -> bool:
    return _hash_password(password, salt) == stored_hash


# ---------------------------------------------------------------------------
# Autenticacion
# ---------------------------------------------------------------------------

def login(username: str, password: str) -> Optional[Dict[str, Any]]:
    """
    Verifica las credenciales. Devuelve el dict del usuario si son correctas,
    None si no. Registra el intento.
    """
    username = username.lower().strip()
    now = datetime.now().isoformat(timespec="seconds")

    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ? AND active = 1",
            (username,),
        ).fetchone()

        if row is None:
            conn.execute(
                "INSERT INTO login_attempts (username, success, timestamp) VALUES (?,0,?)",
                (username, now),
            )
            return None

        if not _verify_password(password, row["salt"], row["password_hash"]):
            conn.execute(
                "INSERT INTO login_attempts (username, success, timestamp) VALUES (?,0,?)",
                (username, now),
            )
            logger.warning("Intento de login fallido para: %s", username)
            return None

        # Login correcto
        conn.execute(
            "UPDATE users SET last_login = ? WHERE id = ?",
            (now, row["id"]),
        )
        conn.execute(
            "INSERT INTO login_attempts (username, success, timestamp) VALUES (?,1,?)",
            (username, now),
        )
        logger.info("Login correcto: %s (%s)", username, row["role"])
        return dict(row)


def has_permission(role: str, permission: str) -> bool:
    return permission in PERMISSIONS.get(role, set())


# ---------------------------------------------------------------------------
# Gestion de usuarios
# ---------------------------------------------------------------------------

def create_user(
    username: str,
    password: str,
    role: str,
    full_name: str = "",
    email: str = "",
) -> bool:
    """Crea un nuevo usuario. Devuelve True si se creo, False si ya existe."""
    if role not in ROLES:
        raise ValueError(f"Rol invalido: {role}. Roles validos: {list(ROLES.keys())}")
    try:
        with _connect() as conn:
            _create_user_internal(conn, username, password, role, full_name, email)
        logger.info("Usuario creado: %s (%s)", username, role)
        return True
    except sqlite3.IntegrityError:
        return False  # Ya existe


def list_users() -> List[Dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, username, role, full_name, email, active, created_at, last_login "
            "FROM users ORDER BY created_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def update_user(
    user_id: int,
    role: Optional[str] = None,
    full_name: Optional[str] = None,
    email: Optional[str] = None,
    active: Optional[bool] = None,
) -> bool:
    fields, values = [], []
    if role      is not None: fields.append("role = ?");      values.append(role)
    if full_name is not None: fields.append("full_name = ?"); values.append(full_name)
    if email     is not None: fields.append("email = ?");     values.append(email)
    if active    is not None: fields.append("active = ?");    values.append(1 if active else 0)
    if not fields:
        return False
    values.append(user_id)
    with _connect() as conn:
        cur = conn.execute(
            f"UPDATE users SET {', '.join(fields)} WHERE id = ?", values
        )
    return cur.rowcount > 0


def change_password(user_id: int, new_password: str) -> bool:
    salt     = secrets.token_hex(32)
    pwd_hash = _hash_password(new_password, salt)
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE users SET password_hash = ?, salt = ? WHERE id = ?",
            (pwd_hash, salt, user_id),
        )
    return cur.rowcount > 0


def delete_user(user_id: int) -> bool:
    with _connect() as conn:
        cur = conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    return cur.rowcount > 0


def get_login_attempts(limit: int = 50) -> List[Dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM login_attempts ORDER BY timestamp DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]
