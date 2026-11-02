# -*- coding: utf-8 -*-
"""
Sistema de autenticacion y roles para TAPIA.

Roles disponibles:
  - admin     : acceso total, gestion de usuarios
  - medico    : acceso a triaje, pacientes, historial
  - consultor : solo lectura (historial y graficas)

Las contrasenas se almacenan con PBKDF2-HMAC-SHA256 + salt. Los hashes antiguos
(SHA-256 de una vuelta) se aceptan y se migran al iniciar sesion.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from ..core import config as _config  # noqa: F401  (carga .env antes de leer variables)

logger = logging.getLogger(__name__)

_DB_PATH = Path(__file__).resolve().parent.parent / "tapia_history.db"

# Clave del admin inicial: .env en local o Secrets en Streamlit Cloud
ADMIN_PASSWORD_ENV = "TAPIA_ADMIN_PASSWORD"
MIN_ADMIN_PASSWORD_LEN = 12

# Clave por defecto publicada en versiones anteriores: nunca debe dar acceso
_LEGACY_DEFAULT_PASSWORD = "tapia1234"

ROLES = {
    "admin":     "Administrador",
    "medico":    "Medico",
    "consultor": "Consultor (solo lectura)",
}

# Permisos por rol
PERMISSIONS = {
    "admin": {
        "triage", "patients", "history", "db_history",
        "compliance", "about", "manage_users", "lifestyle",
    },
    "medico": {
        "triage", "patients", "history", "db_history",
        "compliance", "about", "lifestyle",
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


def _admin_password_from_env() -> Optional[str]:
    """Devuelve la clave del admin inicial si esta definida y es valida."""
    pwd = os.environ.get(ADMIN_PASSWORD_ENV, "").strip()
    if not pwd:
        return None
    if len(pwd) < MIN_ADMIN_PASSWORD_LEN or pwd == _LEGACY_DEFAULT_PASSWORD:
        logger.error(
            "%s no es valida: necesita al menos %d caracteres y no puede ser la clave antigua.",
            ADMIN_PASSWORD_ENV, MIN_ADMIN_PASSWORD_LEN,
        )
        return None
    return pwd


def admin_setup_pending() -> bool:
    """True si aun no existe ningun usuario (falta configurar el admin inicial)."""
    with _connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0


def _ensure_default_admin() -> None:
    """
    Crea el admin inicial con la clave de TAPIA_ADMIN_PASSWORD si no hay usuarios.
    Si el usuario admin aun tiene la clave antigua publicada, la sustituye.
    La clave nunca se escribe en el log.
    """
    pwd = _admin_password_from_env()
    with _connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if count == 0:
            if pwd is None:
                logger.warning(
                    "No hay usuarios y %s no esta definida: no se crea el admin inicial.",
                    ADMIN_PASSWORD_ENV,
                )
                return
            _create_user_internal(conn, "admin", pwd, "admin", "Administrador")
            logger.info("Usuario admin inicial creado desde %s.", ADMIN_PASSWORD_ENV)
            return

        row = conn.execute(
            "SELECT id, salt, password_hash FROM users WHERE username = 'admin'"
        ).fetchone()
        # La clave antigua solo pudo guardarse con el hash antiguo: evita PBKDF2 en cada recarga
        if (
            row
            and _is_legacy_hash(row["password_hash"])
            and _verify_password(_LEGACY_DEFAULT_PASSWORD, row["salt"], row["password_hash"])
        ):
            if pwd is None:
                logger.warning(
                    "El usuario admin aun tiene la clave antigua (bloqueada). "
                    "Define %s para sustituirla.", ADMIN_PASSWORD_ENV,
                )
                return
            salt = secrets.token_hex(32)
            conn.execute(
                "UPDATE users SET password_hash = ?, salt = ? WHERE id = ?",
                (_hash_password(pwd, salt), salt, row["id"]),
            )
            logger.warning("Clave antigua del usuario admin sustituida por %s.", ADMIN_PASSWORD_ENV)


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

_PBKDF2_PREFIX = "pbkdf2_sha256"
PBKDF2_ITERATIONS = 600_000  # recomendacion OWASP para PBKDF2-HMAC-SHA256


def _pbkdf2(password: str, salt: str, iterations: int) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations
    ).hex()


def _hash_password(password: str, salt: str) -> str:
    """Devuelve 'pbkdf2_sha256$iteraciones$hash'."""
    return f"{_PBKDF2_PREFIX}${PBKDF2_ITERATIONS}${_pbkdf2(password, salt, PBKDF2_ITERATIONS)}"


def _legacy_hash(password: str, salt: str) -> str:
    """Hash de versiones anteriores (SHA-256 de una vuelta). Solo para verificar."""
    combined = f"{salt}{password}{salt}"
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()


def _is_legacy_hash(stored_hash: str) -> bool:
    return not stored_hash.startswith(_PBKDF2_PREFIX + "$")


def _needs_rehash(stored_hash: str) -> bool:
    if _is_legacy_hash(stored_hash):
        return True
    return stored_hash.split("$")[1] != str(PBKDF2_ITERATIONS)


def _verify_password(password: str, salt: str, stored_hash: str) -> bool:
    if _is_legacy_hash(stored_hash):
        candidate = _legacy_hash(password, salt)
    else:
        try:
            _, iterations, _ = stored_hash.split("$")
            candidate = f"{_PBKDF2_PREFIX}${iterations}${_pbkdf2(password, salt, int(iterations))}"
        except ValueError:
            return False
    return hmac.compare_digest(candidate, stored_hash)


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
            # Mismo coste que un usuario real para no revelar que no existe
            _hash_password(password, "usuario-inexistente")
            conn.execute(
                "INSERT INTO login_attempts (username, success, timestamp) VALUES (?,0,?)",
                (username, now),
            )
            return None

        if password == _LEGACY_DEFAULT_PASSWORD or not _verify_password(
            password, row["salt"], row["password_hash"]
        ):
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
        if _needs_rehash(row["password_hash"]):
            salt = secrets.token_hex(32)
            conn.execute(
                "UPDATE users SET password_hash = ?, salt = ? WHERE id = ?",
                (_hash_password(password, salt), salt, row["id"]),
            )
            logger.info("Hash de contrasena actualizado a PBKDF2: %s", username)
        conn.execute(
            "INSERT INTO login_attempts (username, success, timestamp) VALUES (?,1,?)",
            (username, now),
        )
        logger.info("Login correcto: %s (%s)", username, row["role"])
        # Nunca devolver el hash ni la sal: el dict acaba en st.session_state
        return {k: row[k] for k in row.keys() if k not in ("password_hash", "salt")}


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
