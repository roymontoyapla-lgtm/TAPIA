"""
Capa de cifrado para datos en reposo.
Usa Fernet (AES-128-CBC + HMAC-SHA256) de la librería `cryptography`.

La clave se genera una sola vez y se guarda en .tapia_key (fuera del repo).
Si el fichero de clave no existe se crea automáticamente al primer uso.
"""

from __future__ import annotations

import base64
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# Ruta de la clave: junto al proyecto, fuera del control de versiones
_KEY_PATH = Path(__file__).resolve().parent.parent / ".tapia_key"

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

def _load_or_create_key() -> bytes:
    """Lee la clave Fernet del fichero, o la genera si no existe."""
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
