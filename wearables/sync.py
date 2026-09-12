# -*- coding: utf-8 -*-
"""
Sincronizacion bajo demanda de los datos del wearable desde la nube.

Descarga los ficheros nuevos que la app del movil ha dejado en el origen
configurado (Dropbox), los normaliza con los adaptadores de siempre y los
importa en la base de datos de forma incremental.

La importacion es idempotente: `import_wearable_records` ignora los dias
que ya existen para ese paciente, asi que se puede pulsar el boton tantas
veces como se quiera sin duplicar nada.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional

from ..db import database as db
from .cloud import CloudFile, CloudSource, CloudSourceError, DropboxSource
from .detector import detect_and_normalize, to_tapia_dicts

logger = logging.getLogger(__name__)

# Tope por sincronizacion para no bloquear la interfaz con un historico enorme
MAX_FILES_PER_SYNC = 30


@dataclass
class SyncResult:
    """Resumen de lo ocurrido en una sincronizacion."""
    files_seen:     int = 0
    files_imported: int = 0
    days_inserted:  int = 0
    days_skipped:   int = 0
    adapters:       List[str] = field(default_factory=list)
    errors:         List[str] = field(default_factory=list)
    last_file:      Optional[str] = None
    pending_files:  int = 0

    @property
    def ok(self) -> bool:
        return self.files_imported > 0 and not self.errors

    def summary(self) -> str:
        """Frase corta para mostrar en la interfaz."""
        if self.files_seen == 0:
            return "No hay ficheros nuevos en el origen configurado."
        partes = [
            f"{self.files_imported} fichero(s) leidos",
            f"{self.days_inserted} dias nuevos",
        ]
        if self.days_skipped:
            partes.append(f"{self.days_skipped} dias ya guardados")
        if self.pending_files:
            partes.append(f"{self.pending_files} fichero(s) pendientes para la proxima vez")
        return " | ".join(partes)


def sync_patient(
    patient_id: int,
    source: Optional[CloudSource] = None,
    since: Optional[str] = None,
    full: bool = False,
    max_files: int = MAX_FILES_PER_SYNC,
) -> SyncResult:
    """
    Descarga e importa los ficheros nuevos del paciente.

    `since` limita a los ficheros modificados despues de esa marca; si no se
    indica, se usa la de la ultima sincronizacion guardada. Con `full=True`
    se releen todos los ficheros del origen (util si se cambio el formato).
    """
    source = source or DropboxSource()
    result = SyncResult()

    if not source.is_configured():
        result.errors.append(
            f"El origen '{source.NAME}' no esta configurado. "
            "Revisa las variables de entorno en el fichero .env."
        )
        return result

    estado = db.get_sync_state(patient_id, source.NAME)
    if since is None and not full and estado:
        since = estado.get("last_modified") or None

    try:
        ficheros: List[CloudFile] = source.list_files(since=since)
    except CloudSourceError as e:
        result.errors.append(str(e))
        return result

    result.files_seen = len(ficheros)
    if not ficheros:
        db.update_sync_state(patient_id, source.NAME)
        return result

    if len(ficheros) > max_files:
        result.pending_files = len(ficheros) - max_files
        ficheros = ficheros[:max_files]

    for fichero in ficheros:
        try:
            crudo = source.download(fichero.path)
            registros, adaptador = detect_and_normalize(_parse(crudo))
        except CloudSourceError as e:
            result.errors.append(f"{fichero.name}: {e}")
            continue
        except ValueError as e:
            # Fichero del que no sabemos el formato: se avisa y se sigue
            result.errors.append(f"{fichero.name}: {e}")
            continue

        if not registros:
            result.errors.append(f"{fichero.name}: no contiene registros validos.")
            continue

        importado = db.import_wearable_records(
            patient_id, to_tapia_dicts(registros), source=adaptador
        )
        result.files_imported += 1
        result.days_inserted  += importado["inserted"]
        result.days_skipped   += importado["skipped"]
        result.last_file       = fichero.name
        if adaptador not in result.adapters:
            result.adapters.append(adaptador)

        db.update_sync_state(
            patient_id, source.NAME,
            last_modified=fichero.modified,
            last_file=fichero.name,
            files_imported=1,
        )

    logger.info(
        "Sincronizacion %s para patient_id=%s: %s",
        source.NAME, patient_id, result.summary(),
    )
    return result


def _parse(raw: bytes):
    """
    Prepara el contenido descargado para el detector: JSON si se puede,
    y si no los bytes tal cual (el XML/ZIP de Apple Health se procesa asi).
    """
    import json
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return raw
