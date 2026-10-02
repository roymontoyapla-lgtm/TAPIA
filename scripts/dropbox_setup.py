# -*- coding: utf-8 -*-
"""
Asistente para dar de alta el acceso a Dropbox.

Hace el flujo OAuth completo y deja las credenciales escritas en el .env:

    python scripts/dropbox_setup.py

Pide la App key y el App secret de la app de Dropbox, abre (o imprime) la
URL de autorizacion, recoge el codigo que muestra el navegador y lo canjea
por un token de refresco, que es el que no caduca. Al final comprueba el
acceso listando los ficheros de la carpeta.

El codigo de autorizacion es de un solo uso y caduca en pocos minutos: si
falla, basta con volver a abrir la URL y pedir uno nuevo.
"""

from __future__ import annotations

import argparse
import getpass
import importlib.util
import re
import sys
from pathlib import Path
from typing import Dict, Optional

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"

AUTHORIZE_URL = (
    "https://www.dropbox.com/oauth2/authorize"
    "?client_id={app_key}&response_type=code&token_access_type=offline"
)
TOKEN_URL = "https://api.dropbox.com/oauth2/token"

# Permisos que necesita TAPIA sobre la carpeta de la app
SCOPES = ("files.metadata.read", "files.content.read")


# ---------------------------------------------------------------------------
# .env
# ---------------------------------------------------------------------------

def read_env(path: Path = ENV_PATH) -> Dict[str, str]:
    """Lee el .env como diccionario. Devuelve {} si no existe."""
    if not path.exists():
        return {}
    valores: Dict[str, str] = {}
    for linea in path.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, _, valor = linea.partition("=")
        valores[clave.strip()] = valor.strip().strip('"').strip("'")
    return valores


def update_env_text(texto: str, nuevos: Dict[str, str]) -> str:
    """
    Devuelve el contenido del .env con `nuevos` aplicados: sustituye las
    claves que ya existen (conservando su sitio) y anade las que faltan.
    """
    lineas = texto.splitlines() if texto else []
    pendientes = dict(nuevos)

    for i, linea in enumerate(lineas):
        limpia = linea.strip()
        if not limpia or limpia.startswith("#") or "=" not in limpia:
            continue
        clave = limpia.split("=", 1)[0].strip()
        if clave in pendientes:
            lineas[i] = f"{clave}={pendientes.pop(clave)}"

    if pendientes:
        if lineas and lineas[-1].strip():
            lineas.append("")
        lineas.append("# --- Dropbox (generado por scripts/dropbox_setup.py) ---")
        lineas += [f"{c}={v}" for c, v in pendientes.items()]

    return "\n".join(lineas) + "\n"


def write_env(nuevos: Dict[str, str], path: Path = ENV_PATH) -> None:
    texto = path.read_text(encoding="utf-8") if path.exists() else ""
    path.write_text(update_env_text(texto, nuevos), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Dependencias
# ---------------------------------------------------------------------------

def check_requirements() -> None:
    """
    Comprueba `requests` ANTES de pedir nada.

    El codigo de autorizacion es de un solo uso: si esto fallara al canjear,
    habria que repetir toda la autorizacion desde el navegador.
    """
    if importlib.util.find_spec("requests") is None:
        raise SystemExit(
            "\nFalta la libreria 'requests'. Instalala y vuelve a ejecutar:\n\n"
            "    python -m pip install requests\n\n"
            "(o de una vez todas las dependencias del proyecto:\n"
            "    python -m pip install -r requirements.txt)\n"
        )


# ---------------------------------------------------------------------------
# OAuth
# ---------------------------------------------------------------------------

# La App key y el App secret son 15 caracteres en minuscula; el codigo de
# autorizacion es mucho mas largo y mezcla mayusculas. Confundirlos es el
# error tipico, asi que se corta antes de gastar el canje.
_CREDENCIAL_PANEL = re.compile(r"^[a-z0-9]{15}$")


def validate_code(code: str, app_key: str = "", app_secret: str = "") -> None:
    """Aborta si lo pegado no parece un codigo de autorizacion."""
    if code and code == app_key:
        raise SystemExit(
            "\nEso es tu App key, no el codigo de autorizacion.\n"
            "El codigo sale en el navegador despues de pulsar 'Permitir'.\n"
        )
    if code and code == app_secret:
        raise SystemExit(
            "\nEso es tu App secret, no el codigo de autorizacion.\n"
            "Regeneralo en dropbox.com/developers/apps si lo has pegado en algun\n"
            "sitio visible, y copia el codigo que sale en el navegador tras\n"
            "pulsar 'Permitir'.\n"
        )
    if _CREDENCIAL_PANEL.match(code):
        raise SystemExit(
            "\nEsto parece una credencial del panel de Dropbox (15 caracteres),\n"
            "no un codigo de autorizacion.\n\n"
            "  App key / App secret : 15 caracteres, todo en minuscula\n"
            "  Codigo de autorizacion: mucho mas largo, mezcla mayusculas\n\n"
            "Abre la URL de autorizacion, pulsa 'Permitir' y copia la cadena\n"
            "larga que aparece en la caja 'Codigo de acceso generado'.\n"
        )


def exchange_code(app_key: str, app_secret: str, code: str) -> Dict[str, str]:
    """Canjea el codigo de autorizacion por un token de refresco."""
    import requests

    resp = requests.post(
        TOKEN_URL,
        data={"code": code, "grant_type": "authorization_code"},
        auth=(app_key, app_secret),
        timeout=30,
    )
    datos = {}
    try:
        datos = resp.json()
    except ValueError:
        pass

    if resp.status_code != 200:
        error = datos.get("error_description") or datos.get("error") or resp.text[:200]
        if "invalid_grant" in str(error) or "expired" in str(error).lower():
            raise SystemExit(
                "\nDropbox rechaza el codigo: ya se habia usado o ha caducado.\n"
                "Vuelve a abrir la URL de autorizacion y pega el codigo nuevo.\n"
            )
        raise SystemExit(f"\nDropbox devolvio {resp.status_code}: {error}\n")

    if not datos.get("refresh_token"):
        raise SystemExit(
            "\nLa respuesta no incluye refresh_token. Comprueba que la URL de\n"
            "autorizacion llevaba 'token_access_type=offline'.\n"
        )
    return datos


def check_access(app_key: str, app_secret: str, refresh_token: str) -> None:
    """Lista la carpeta de la app usando el codigo real de TAPIA."""
    if "tapia" not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            "tapia", ROOT / "__init__.py", submodule_search_locations=[str(ROOT)],
        )
        modulo = importlib.util.module_from_spec(spec)
        sys.modules["tapia"] = modulo
        spec.loader.exec_module(modulo)

    from tapia.core.config import cfg
    from tapia.wearables.cloud import CloudSourceError, DropboxSource

    source = DropboxSource(
        folder=cfg.wearable_sync.folder,
        extensions=tuple(cfg.wearable_sync.extensions),
        app_key=app_key, app_secret=app_secret,
        refresh_token=refresh_token, access_token="",
    )
    try:
        ficheros = source.list_files()
    except CloudSourceError as e:
        print(f"\n  El token funciona a medias: {e}")
        return

    carpeta = cfg.wearable_sync.folder or "/ (raiz de la carpeta de la app)"
    if ficheros:
        print(f"\n  Acceso correcto. {len(ficheros)} fichero(s) en {carpeta}:")
        for f in ficheros[-5:]:
            print(f"    - {f.name}  ({f.modified})")
    else:
        print(
            f"\n  Acceso correcto, pero {carpeta} esta vacia todavia.\n"
            "  Configura la automatizacion de Health Auto Export para que exporte ahi."
        )


# ---------------------------------------------------------------------------
# Interfaz
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Alta del acceso a Dropbox para TAPIA.")
    parser.add_argument("--app-key",    help="App key de la app de Dropbox")
    parser.add_argument("--app-secret", help="App secret de la app de Dropbox")
    parser.add_argument("--code",       help="Codigo de autorizacion ya obtenido")
    parser.add_argument("--no-write",   action="store_true",
                        help="Solo imprime el token, no toca el .env")
    args = parser.parse_args()

    check_requirements()
    env = read_env()

    print("\n=== Alta del acceso a Dropbox para TAPIA ===\n")
    print("Antes de empezar, en dropbox.com/developers/apps tu app debe tener:")
    print("  - Acceso 'App folder' (no 'Full Dropbox')")
    print(f"  - Permisos: {', '.join(SCOPES)} (pestana Permissions)\n")

    app_key = args.app_key or env.get("DROPBOX_APP_KEY") or input("App key: ").strip()
    if not app_key:
        raise SystemExit("Hace falta la App key.")

    app_secret = args.app_secret or env.get("DROPBOX_APP_SECRET")
    if app_secret:
        print("App secret: (tomado del .env)")
    else:
        app_secret = getpass.getpass("App secret (no se muestra): ").strip()
    if not app_secret:
        raise SystemExit("Hace falta el App secret.")

    code = args.code
    if not code:
        print("\n1) Abre esta URL en el navegador y pulsa 'Permitir':\n")
        print("   " + AUTHORIZE_URL.format(app_key=app_key))
        print("\n2) Copia el codigo que aparece en pantalla y pegalo aqui.")
        print("   (es de un solo uso y caduca en pocos minutos)\n")
        code = input("Codigo: ").strip()
    if not code:
        raise SystemExit("Hace falta el codigo de autorizacion.")

    # Por si se pega la URL entera en vez del codigo
    encontrado = re.search(r"auth_code=([^&\s]+)", code)
    if encontrado:
        code = encontrado.group(1)

    validate_code(code, app_key, app_secret)

    print("\nCanjeando el codigo...")
    datos = exchange_code(app_key, app_secret, code)
    refresh_token = datos["refresh_token"]

    concedidos = set((datos.get("scope") or "").split())
    faltan = [s for s in SCOPES if s not in concedidos] if concedidos else []
    if faltan:
        print(
            "\n  Aviso: a este token le faltan permisos (" + ", ".join(faltan) + ").\n"
            "  Anadelos en la pestana Permissions y repite la autorizacion."
        )

    if args.no_write:
        print("\nRefresh token (guardalo en el .env como DROPBOX_REFRESH_TOKEN):\n")
        print("  " + refresh_token + "\n")
    else:
        write_env({
            "DROPBOX_APP_KEY":       app_key,
            "DROPBOX_APP_SECRET":    app_secret,
            "DROPBOX_REFRESH_TOKEN": refresh_token,
        })
        print(f"\nCredenciales guardadas en {ENV_PATH}")
        print("(el .env esta en .gitignore: no se sube al repositorio)")

    check_access(app_key, app_secret, refresh_token)

    print("\nListo. En TAPIA: Triaje -> nombre del paciente -> 'Cargar desde Dropbox'.\n")


if __name__ == "__main__":
    main()
