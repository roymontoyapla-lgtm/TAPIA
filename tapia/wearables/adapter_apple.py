# -*- coding: utf-8 -*-
"""
Adaptador para exportaciones de Apple Health.

Apple Health exporta un fichero export.xml, pero muchas apps
(como Health Auto Export) permiten exportar un JSON con esta estructura:

[
  {
    "date": "2024-03-01",
    "HKQuantityTypeIdentifierRestingHeartRate": 62,
    "HKQuantityTypeIdentifierStepCount": 7500,
    "HKCategoryTypeIdentifierSleepAnalysis_asleep": 7.2,
    "HKQuantityTypeIdentifierAppleExerciseTime": 35,
    "HKQuantityTypeIdentifierHeartRateVariabilitySDNN": 42,
    "HKQuantityTypeIdentifierRespiratoryRate": 15
  }
]

O formato simplificado:
[
  {
    "date": "2024-03-01",
    "restingHeartRate": 62,
    "steps": 7500,
    "sleepHours": 7.2,
    "exerciseMinutes": 35,
    "hrv": 42
  }
]
"""

from __future__ import annotations

from typing import Any, List

from .base import BaseAdapter, NormalizedRecord

# Claves HK completas de Apple Health
_HK_HR    = "HKQuantityTypeIdentifierRestingHeartRate"
_HK_STEPS = "HKQuantityTypeIdentifierStepCount"
_HK_SLEEP = "HKCategoryTypeIdentifierSleepAnalysis_asleep"
_HK_EX    = "HKQuantityTypeIdentifierAppleExerciseTime"
_HK_HRV   = "HKQuantityTypeIdentifierHeartRateVariabilitySDNN"
_HK_RESP  = "HKQuantityTypeIdentifierRespiratoryRate"


class AppleHealthAdapter(BaseAdapter):
    NAME = "apple_health"
    DESCRIPTION = "Exportacion Apple Health"

    def can_handle(self, data: Any) -> bool:
        if not isinstance(data, list) or not data:
            return False
        first = data[0]
        if not isinstance(first, dict):
            return False
        # Apple Health usa "date" como campo de fecha
        has_date = "date" in first
        has_hk   = any(k.startswith("HK") for k in first)
        has_simple = any(k in first for k in ["restingHeartRate", "steps", "sleepHours"])
        return has_date and (has_hk or has_simple)

    def normalize(self, data: Any) -> List[NormalizedRecord]:
        records = []
        for r in data:
            if not isinstance(r, dict) or "date" not in r:
                continue

            fecha = str(r["date"])[:10]  # solo YYYY-MM-DD

            # Intentar claves HK completas primero, luego simplificadas
            hr    = _f(r.get(_HK_HR)    or r.get("restingHeartRate"))
            steps = _f(r.get(_HK_STEPS) or r.get("steps"))
            sleep = _f(r.get(_HK_SLEEP) or r.get("sleepHours"))
            ex    = _f(r.get(_HK_EX)    or r.get("exerciseMinutes"))
            hrv   = _f(r.get(_HK_HRV)   or r.get("hrv"))
            resp  = _f(r.get(_HK_RESP)  or r.get("respiratoryRate"))

            records.append(NormalizedRecord(
                fecha=fecha,
                pulso_reposo_bpm_media=hr,
                pasos=steps,
                min_ejercicio=ex,
                sueno_asleep_horas=sleep,
                respiraciones_por_min_media=resp,
                hrv_sdnn_ms_media=hrv,
            ))
        return records


def _f(v: Any):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None
