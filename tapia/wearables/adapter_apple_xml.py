# -*- coding: utf-8 -*-
"""
Adaptador para el XML nativo de Apple Health (export.xml / exportacion.xml).

Procesa el XML por streaming (iterparse) para manejar ficheros de varios GB
sin cargar todo en memoria. Devuelve registros normalizados por dia.

Tambien acepta directamente el ZIP que exporta el iPhone (contiene el XML
comprimido). Subir el ZIP en vez del XML descomprimido es MUCHO mas rapido
(el XML de Apple Health comprime tipicamente a menos del 10% de su tamano).
"""

from __future__ import annotations

import io
import zipfile
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, List, Optional, Tuple

from .base import BaseAdapter, NormalizedRecord

# Tipos de registro que nos interesan
_RECORD_TYPES = {
    "HKQuantityTypeIdentifierRestingHeartRate":         "hr",
    "HKQuantityTypeIdentifierStepCount":                "steps",
    "HKQuantityTypeIdentifierAppleExerciseTime":        "exercise",
    "HKQuantityTypeIdentifierRespiratoryRate":          "resp",
    "HKQuantityTypeIdentifierHeartRateVariabilitySDNN": "hrv",
}

_SLEEP_TYPE = "HKCategoryTypeIdentifierSleepAnalysis"
_SLEEP_ASLEEP = {
    "HKCategoryValueSleepAnalysisAsleep",
    "HKCategoryValueSleepAnalysisAsleepCore",
    "HKCategoryValueSleepAnalysisAsleepDeep",
    "HKCategoryValueSleepAnalysisAsleepREM",
}


class AppleHealthXMLAdapter(BaseAdapter):
    NAME = "apple_health_xml"
    DESCRIPTION = "Apple Health XML (export.xml)"

    def can_handle(self, data: Any) -> bool:
        """
        Detecta si los datos son bytes de un XML de Apple Health,
        o un ZIP que contiene dicho XML (formato de exportacion del iPhone).
        """
        if not isinstance(data, (bytes, bytearray)):
            return False
        # ZIP: firma PK
        if data[:2] == b"PK":
            xml_name = _find_health_xml_in_zip(data)
            return xml_name is not None
        try:
            header = data[:2048].decode("utf-8", errors="ignore")
            return "HealthData" in header or "HealthKit" in header
        except Exception:
            return False

    def normalize(self, data: Any, days: int = 180) -> List[NormalizedRecord]:
        """
        Parsea el XML (o el XML dentro del ZIP) por streaming y devuelve
        registros normalizados. Solo incluye los ultimos `days` dias.
        """
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        daily  = defaultdict(lambda: {
            "hrs": [], "steps": [], "exercise": [],
            "resps": [], "hrvs": [], "sleep_h": 0.0,
        })

        stream = _open_xml_stream(data)
        context = ET.iterparse(stream, events=("end",))

        for _, elem in context:
            if elem.tag != "Record":
                elem.clear()
                continue

            rtype = elem.get("type", "")
            start = elem.get("startDate", "")[:10]

            if start < cutoff:
                elem.clear()
                continue

            val = elem.get("value", "")

            if rtype in _RECORD_TYPES:
                key = _RECORD_TYPES[rtype]
                try:
                    v = float(val)
                    if key == "hr":       daily[start]["hrs"].append(v)
                    elif key == "steps":  daily[start]["steps"].append(v)
                    elif key == "exercise": daily[start]["exercise"].append(v)
                    elif key == "resp":   daily[start]["resps"].append(v)
                    elif key == "hrv":    daily[start]["hrvs"].append(v)
                except (ValueError, TypeError):
                    pass

            elif rtype == _SLEEP_TYPE:
                if elem.get("value", "") in _SLEEP_ASLEEP:
                    h = _duration_hours(
                        elem.get("startDate", ""),
                        elem.get("endDate",   ""),
                    )
                    daily[start]["sleep_h"] += h

            elem.clear()

        return [_to_record(fecha, d) for fecha in sorted(daily.keys())
                if (d := daily[fecha])]


def _find_health_xml_in_zip(zip_bytes: bytes) -> Optional[str]:
    """
    Busca dentro del ZIP el fichero XML de Apple Health (export.xml o similar),
    ignorando export_cda.xml (formato clinico distinto que no nos interesa).
    Devuelve el nombre del fichero dentro del ZIP, o None si no se encuentra.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            candidates = [
                n for n in zf.namelist()
                if n.lower().endswith(".xml") and "cda" not in n.lower()
            ]
            if not candidates:
                return None
            # Preferir el que contenga "export" en el nombre
            for c in candidates:
                if "export" in c.lower():
                    return c
            return candidates[0]
    except zipfile.BadZipFile:
        return None


def _open_xml_stream(data: bytes):
    """
    Devuelve un objeto tipo fichero listo para iterparse.
    Si `data` es un ZIP, extrae el XML de Apple Health en streaming
    (sin descomprimir todo el ZIP en memoria de golpe).
    Si es un XML plano, lo envuelve directamente.
    """
    if data[:2] == b"PK":
        zf = zipfile.ZipFile(io.BytesIO(data))
        xml_name = _find_health_xml_in_zip(data)
        if xml_name is None:
            raise ValueError("El ZIP no contiene un XML de Apple Health valido.")
        return zf.open(xml_name)
    return io.BytesIO(data)


def _duration_hours(start_str: str, end_str: str) -> float:
    fmt = "%Y-%m-%d %H:%M:%S %z"
    try:
        s = datetime.strptime(start_str, fmt)
        e = datetime.strptime(end_str,   fmt)
        return max(0.0, (e - s).total_seconds() / 3600)
    except Exception:
        return 0.0


def _avg(lst: list) -> Optional[float]:
    return round(sum(lst) / len(lst), 2) if lst else None


def _to_record(fecha: str, d: dict) -> NormalizedRecord:
    return NormalizedRecord(
        fecha=fecha,
        pulso_reposo_bpm_media=_avg(d["hrs"]),
        pasos=round(sum(d["steps"]), 0) if d["steps"] else None,
        min_ejercicio=round(sum(d["exercise"]), 1) if d["exercise"] else None,
        sueno_asleep_horas=round(d["sleep_h"], 2) if d["sleep_h"] > 0 else None,
        respiraciones_por_min_media=_avg(d["resps"]),
        hrv_sdnn_ms_media=_avg(d["hrvs"]),
    )
