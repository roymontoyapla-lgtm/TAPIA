"""
Capa de cifrado para datos en reposo.
Usa Fernet (AES-128-CBC + HMAC-SHA256) de la librería `cryptography`.

Origen de la clave, por orden:
  1. Variable TAPIA_ENCRYPTION_KEY (Secrets de Streamlit Cloud o .env). Necesaria
     en la nube, donde el disco se borra en cada reinicio.
  2. Fichero .tapia_key (fuera del repo). Si no existe se crea al primer uso.
"""

from __future__ import annotations

import base64
import logging
import os
from pathlib import Path

from ..core import config as _config  # noqa: F401  (carga .env antes de leer variables)

logger = logging.getLogger(__name__)

# Ruta de la clave: junto al proyecto, fuera del control de versiones
_KEY_PATH = Path(__file__).resolve().parent.parent / ".tapia_key"

KEY_ENV = "TAPIA_ENCRYPTION_KEY"

try:
    from cryptography.fernet import Fernet, InvalidToken
    _CRYPTO_OK = True
except ImportError:
    _CRYPTO_OK = False
    logger.warning(
        "cryptography no instalada. Los datos se guardarán sin cifrar.\n"
        "Instala con: pip install cryptography"
    )


# ---------------------------------------------------------------------------
# Gestión de la clave
# ---------------------------------------------------------------------------

def _key_from_env() -> bytes | None:
    """
    Clave de TAPIA_ENCRYPTION_KEY, o None si no esta definida.
    Si esta mal formada lanza ValueError: generar otra en silencio dejaria
    ilegibles los datos cifrados con la buena.
    """
    raw = os.environ.get(KEY_ENV, "").strip()
    if not raw:
        return None
    try:
        Fernet(raw.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as e:
        raise ValueError(
            f"{KEY_ENV} no es una clave Fernet valida (44 caracteres base64)."
        ) from e
    return raw.encode("ascii")


def _load_or_create_key() -> bytes:
    """Lee la clave de la variable de entorno o del fichero; si no hay, la genera."""
    env_key = _key_from_env()
    if env_key is not None:
        return env_key
    if _KEY_PATH.exists():
        key = _KEY_PATH.read_bytes().strip()
        logger.debug("Clave de cifrado cargada desde %s", _KEY_PATH)
        return key
    else:
        key = Fernet.generate_key()
        _KEY_PATH.write_bytes(key)
        # Solo el propietario puede leer/escribir
        _KEY_PATH.chmod(0o600)
        logger.info("Nueva clave de cifrado generada en %s", _KEY_PATH)
        return key


def _get_fernet() -> "Fernet":
    key = _load_or_create_key()
    return Fernet(key)


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

def encrypt(plaintext: str) -> str:
    """
    Cifra un string UTF-8 y devuelve el token Fernet como string.
    Si cryptography no está disponible devuelve el texto tal cual
    (degradación elegante, con advertencia).
    """
    if not _CRYPTO_OK:
        return plaintext
    f = _get_fernet()
    token = f.encrypt(plaintext.encode("utf-8"))
    return token.decode("ascii")


def decrypt(token: str) -> str:
    """
    Descifra un token Fernet y devuelve el texto original.
    Lanza ValueError si el token es inválido o la clave no coincide.
    """
    if not _CRYPTO_OK:
        return token
    try:
        f = _get_fernet()
        return f.decrypt(token.encode("ascii")).decode("utf-8")
    except Exception as e:
        raise ValueError(f"No se pudo descifrar el dato: {e}") from e


def is_available() -> bool:
    """True si el cifrado está operativo."""
    return _CRYPTO_OK


def key_path() -> str:
    """Ruta al fichero de clave (para mostrarlo en la UI)."""
    return str(_KEY_PATH)


def key_location() -> str:
    """Describe de donde sale la clave, sin revelarla (para la UI)."""
    if os.environ.get(KEY_ENV, "").strip():
        return f"variable {KEY_ENV}"
    return key_path()
