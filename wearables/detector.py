# -*- coding: utf-8 -*-
"""
Detector automatico de formato de wearable.
Prueba cada adaptador en orden hasta encontrar uno que pueda manejar los datos.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .adapter_tapia    import TapiaAdapter
from .adapter_apple_xml import AppleHealthXMLAdapter
from .adapter_fitbit   import FitbitAdapter
from .adapter_garmin   import GarminAdapter
from .adapter_apple    import AppleHealthAdapter
from .adapter_withings import WithingsAdapter
from .base import BaseAdapter, NormalizedRecord

logger = logging.getLogger(__name__)

# Orden de deteccion: del mas especifico al mas generico
_ADAPTERS: List[BaseAdapter] = [
    AppleHealthXMLAdapter(),  # XML nativo Apple Health (bytes)
    FitbitAdapter(),
    GarminAdapter(),
    WithingsAdapter(),
    AppleHealthAdapter(),
    TapiaAdapter(),   # siempre al final como fallback
]

# Mapa de nombres para mostrar en la UI
ADAPTER_NAMES: Dict[str, str] = {a.NAME: a.DESCRIPTION for a in _ADAPTERS}


def detect_and_normalize(data: Any) -> Tuple[List[NormalizedRecord], str]:
    """
    Detecta automaticamente el formato y normaliza los datos.
    Devuelve (registros_normalizados, nombre_del_adaptador).
    Lanza ValueError si ningun adaptador puede manejar los datos.
    """
    for adapter in _ADAPTERS:
        if adapter.can_handle(data):
            logger.info("Formato detectado: %s", adapter.NAME)
            records = adapter.normalize(data)
            logger.info("Registros normalizados: %d", len(records))
            return records, adapter.NAME

    raise ValueError(
        "Formato de wearable no reconocido. "
        "Formatos soportados: TAPIA, Fitbit, Garmin, Apple Health, Withings."
    )


def to_tapia_dicts(records: List[NormalizedRecord]) -> List[Dict[str, Any]]:
    """Convierte registros normalizados al formato dict que usa el resto de TAPIA."""
    return [r.to_dict() for r in records]


def load_and_detect(json_bytes: bytes) -> Tuple[List[Dict[str, Any]], str]:
    """
    Carga un JSON desde bytes, detecta el formato y devuelve
    (lista_de_dicts_en_formato_tapia, nombre_del_adaptador).
    """
    try:
        data = json.loads(json_bytes.decode("utf-8"))
    except Exception as e:
        raise ValueError(f"El fichero no es un JSON valido: {e}") from e

    records, adapter_name = detect_and_normalize(data)
    return to_tapia_dicts(records), adapter_name
