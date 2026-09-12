# -*- coding: utf-8 -*-
"""
Origenes en la nube desde los que TAPIA puede descargar datos de wearable.

Apple Health no tiene API en la nube: HealthKit vive en el iPhone. La via
practica es que una app del movil (Health Auto Export y similares) deje los
ficheros JSON en una carpeta de Dropbox de forma automatica, y que TAPIA los
lea cuando el profesional pulsa el boton de sincronizar.

Se usa `requests` (que ya viene con Streamlit) en lugar del SDK de Dropbox
para no anadir dependencias al despliegue.

Configuracion por variables de entorno (fichero .env):

    DROPBOX_APP_KEY, DROPBOX_APP_SECRET, DROPBOX_REFRESH_TOKEN
        Credenciales de una app de Dropbox con permiso de solo lectura
        sobre su carpeta. Es la opcion recomendada: el token de refresco
        no caduca.

    DROPBOX_ACCESS_TOKEN
        Alternativa rapida para pruebas. Los tokens generados desde el
        panel de Dropbox caducan a las pocas horas.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_TOKEN_URL    = "https://api.dropbox.com/oauth2/token"
_LIST_URL     = "https://api.dropboxapi.com/2/files/list_folder"
_CONTINUE_URL = "https://api.dropboxapi.com/2/files/list_folder/continue"
_DOWNLOAD_URL = "https://content.dropboxapi.com/2/files/download"

_TIMEOUT = 30


class CloudSourceError(RuntimeError):
    """Fallo al hablar con el proveedor de almacenamiento."""


@dataclass
class CloudFile:
    """Un fichero disponible en el origen remoto."""
    path:     str
    name:     str
    modified: str          # ISO-8601 tal cual lo devuelve el proveedor
    size:     int = 0


class CloudSource:
    """Interfaz comun de los origenes en la nube."""

    NAME = "cloud"
    DESCRIPTION = "Origen generico"

    def is_configured(self) -> bool:
        raise NotImplementedError

    def list_files(self, since: Optional[str] = None) -> List[CloudFile]:
        """Ficheros disponibles, del mas antiguo al mas reciente."""
        raise NotImplementedError

    def download(self, path: str) -> bytes:
        raise NotImplementedError


class DropboxSource(CloudSource):
    """Lee los ficheros que la app del movil deja en una carpeta de Dropbox."""

    NAME = "dropbox"
    DESCRIPTION = "Dropbox (Apple Health via Health Auto Export)"

    def __init__(
        self,
        folder: str = "",
        extensions: tuple = (".json",),
        app_key: Optional[str] = None,
        app_secret: Optional[str] = None,
        refresh_token: Optional[str] = None,
        access_token: Optional[str] = None,
    ) -> None:
        # "" es la raiz de la carpeta de la app en Dropbox
        self.folder     = (folder or "").rstrip("/")
        self.extensions = tuple(e.lower() for e in extensions)
        self._app_key       = app_key       if app_key       is not None else os.getenv("DROPBOX_APP_KEY", "")
        self._app_secret    = app_secret    if app_secret    is not None else os.getenv("DROPBOX_APP_SECRET", "")
        self._refresh_token = refresh_token if refresh_token is not None else os.getenv("DROPBOX_REFRESH_TOKEN", "")
        self._access_token  = access_token  if access_token  is not None else os.getenv("DROPBOX_ACCESS_TOKEN", "")

    # -- configuracion ------------------------------------------------------

    def is_configured(self) -> bool:
        tiene_refresco = bool(self._app_key and self._app_secret and self._refresh_token)
        return tiene_refresco or bool(self._access_token)

    def missing_config(self) -> List[str]:
        """Variables de entorno que faltan, para poder avisar en la interfaz."""
        if self.is_configured():
            return []
        if self._access_token:
            return []
        faltan = []
        for nombre, valor in (
            ("DROPBOX_APP_KEY",       self._app_key),
            ("DROPBOX_APP_SECRET",    self._app_secret),
            ("DROPBOX_REFRESH_TOKEN", self._refresh_token),
        ):
            if not valor:
                faltan.append(nombre)
        return faltan

    # -- autenticacion ------------------------------------------------------

    def _token(self) -> str:
        """Token de acceso valido, renovandolo si hay token de refresco."""
        if self._refresh_token and self._app_key and self._app_secret:
            requests = _requests()
            try:
                resp = requests.post(
                    _TOKEN_URL,
                    data={"grant_type": "refresh_token", "refresh_token": self._refresh_token},
                    auth=(self._app_key, self._app_secret),
                    timeout=_TIMEOUT,
                )
            except Exception as e:
                raise CloudSourceError(f"No se pudo contactar con Dropbox: {e}") from e
            if resp.status_code != 200:
                raise CloudSourceError(
                    f"Dropbox rechazo el token de refresco ({resp.status_code}). "
                    "Revisa DROPBOX_APP_KEY, DROPBOX_APP_SECRET y DROPBOX_REFRESH_TOKEN."
                )
            token = (resp.json() or {}).get("access_token", "")
            if not token:
                raise CloudSourceError("Dropbox no devolvio ningun token de acceso.")
            return token

        if self._access_token:
            return self._access_token

        raise CloudSourceError(
            "Dropbox no esta configurado. Define DROPBOX_APP_KEY, DROPBOX_APP_SECRET "
            "y DROPBOX_REFRESH_TOKEN en el fichero .env."
        )

    # -- operaciones --------------------------------------------------------

    def list_files(self, since: Optional[str] = None) -> List[CloudFile]:
        """
        Ficheros de la carpeta con la extension configurada. Si `since` trae
        una fecha ISO, solo devuelve los modificados despues de esa marca.
        """
        requests = _requests()
        token = self._token()
        cabeceras = {
            "Authorization": f"Bearer {token}",
            "Content-Type":  "application/json",
        }

        ficheros: List[CloudFile] = []
        cuerpo: Dict[str, Any] = {"path": self.folder, "recursive": True, "limit": 500}
        url = _LIST_URL

        while True:
            try:
                resp = requests.post(url, headers=cabeceras, json=cuerpo, timeout=_TIMEOUT)
            except Exception as e:
                raise CloudSourceError(f"No se pudo listar la carpeta de Dropbox: {e}") from e
            if resp.status_code != 200:
                raise CloudSourceError(
                    f"Dropbox devolvio {resp.status_code} al listar la carpeta "
                    f"'{self.folder or '/'}': {resp.text[:200]}"
                )

            datos = resp.json() or {}
            for entrada in datos.get("entries", []):
                if entrada.get(".tag") != "file":
                    continue
                nombre = entrada.get("name", "")
                if self.extensions and not nombre.lower().endswith(self.extensions):
                    continue
                modificado = entrada.get("server_modified", "") or ""
                if since and modificado and modificado <= since:
                    continue
                ficheros.append(CloudFile(
                    path=entrada.get("path_lower") or entrada.get("path_display", ""),
                    name=nombre,
                    modified=modificado,
                    size=int(entrada.get("size", 0) or 0),
                ))

            if not datos.get("has_more"):
                break
            url, cuerpo = _CONTINUE_URL, {"cursor": datos.get("cursor")}

        ficheros.sort(key=lambda f: (f.modified, f.name))
        logger.info("Dropbox: %d ficheros nuevos en '%s'", len(ficheros), self.folder or "/")
        return ficheros

    def download(self, path: str) -> bytes:
        requests = _requests()
        cabeceras = {
            "Authorization":   f"Bearer {self._token()}",
            "Dropbox-API-Arg": json.dumps({"path": path}),
        }
        try:
            resp = requests.post(_DOWNLOAD_URL, headers=cabeceras, timeout=_TIMEOUT)
        except Exception as e:
            raise CloudSourceError(f"No se pudo descargar '{path}': {e}") from e
        if resp.status_code != 200:
            raise CloudSourceError(
                f"Dropbox devolvio {resp.status_code} al descargar '{path}': {resp.text[:200]}"
            )
        return resp.content


def _requests():
    """Importa requests en el momento de usarlo, con un error claro si falta."""
    try:
        import requests
        return requests
    except ImportError as e:  # pragma: no cover - requests viene con Streamlit
        raise CloudSourceError(
            "La libreria 'requests' no esta instalada. Instala con: pip install requests"
        ) from e


def get_source(name: str = "dropbox", **kwargs) -> CloudSource:
    """Devuelve el origen en la nube pedido."""
    if name.lower() == "dropbox":
        return DropboxSource(**kwargs)
    raise ValueError(f"Origen en la nube no soportado: {name}")
