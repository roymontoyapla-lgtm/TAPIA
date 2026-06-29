# -*- coding: utf-8 -*-
"""
Adaptador para el XML nativo de Apple Health (export.xml / exportacion.xml).

Procesa el XML por streaming (iterparse) para manejar ficheros de varios GB
sin cargar todo en memoria. Devuelve registros normalizados por dia.
"""

from __future__ import annotations

import io
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
        Detecta si los datos son bytes de un XML de Apple Health.
        Busca la firma 'HealthData' en los primeros 2KB.
        """
        if not isinstance(data, (bytes, bytearray)):
            return False
        try:
            header = data[:2048].decode("utf-8", errors="ignore")
            return "HealthData" in header or "HealthKit" in header
        except Exception:
            return False

    def normalize(self, data: Any, days: int = 180) -> List[NormalizedRecord]:
        """
        Parsea el XML por streaming y devuelve registros normalizados.
        Solo incluye los ultimos `days` dias.
        """
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        daily  = defaultdict(lambda: {
            "hrs": [], "steps": [], "exercise": [],
            "resps": [], "hrvs": [], "sleep_h": 0.0,
        })

        stream  = io.BytesIO(data)
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
