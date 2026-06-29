# -*- coding: utf-8 -*-
"""
Adaptador para exportaciones de Garmin Connect.

Garmin exporta actividades diarias en formato JSON con esta estructura:
{
  "allMetrics": {
    "metricsMap": {
      "WELLNESS_RESTING_HEART_RATE": [{"value": 62, "calendarDate": "2024-03-01"}],
      "WELLNESS_TOTAL_STEPS":        [{"value": 7500, ...}],
      ...
    }
  }
}

O en formato de lista diaria simplificada:
[
  {
    "calendarDate": "2024-03-01",
    "restingHeartRate": 62,
    "totalSteps": 7500,
    "sleepingSeconds": 25200,
    "moderateIntensityMinutes": 20,
    "vigorousIntensityMinutes": 15
  }
]
"""

from __future__ import annotations

from typing import Any, List

from .base import BaseAdapter, NormalizedRecord


class GarminAdapter(BaseAdapter):
    NAME = "garmin"
    DESCRIPTION = "Exportacion Garmin Connect"

    def can_handle(self, data: Any) -> bool:
        if isinstance(data, list) and data:
            first = data[0]
            return isinstance(first, dict) and "calendarDate" in first
        if isinstance(data, dict):
            return "allMetrics" in data or "calendarDate" in data
        return False

    def normalize(self, data: Any) -> List[NormalizedRecord]:
        # Formato lista diaria simplificada
        if isinstance(data, list):
            return self._from_list(data)
        # Formato allMetrics
        if isinstance(data, dict) and "allMetrics" in data:
            return self._from_all_metrics(data)
        return []

    def _from_list(self, data: List) -> List[NormalizedRecord]:
        records = []
        for r in data:
            if not isinstance(r, dict):
                continue
            fecha = r.get("calendarDate", "")

            sleep_sec = _f(r.get("sleepingSeconds"))
            sleep_h   = round(sleep_sec / 3600, 2) if sleep_sec else None

            mod = _f(r.get("moderateIntensityMinutes", 0)) or 0
            vig = _f(r.get("vigorousIntensityMinutes", 0)) or 0
            min_ej = mod + vig if (mod + vig) > 0 else None

            records.append(NormalizedRecord(
                fecha=str(fecha),
                pulso_reposo_bpm_media=_f(r.get("restingHeartRate")),
                pasos=_f(r.get("totalSteps")),
                min_ejercicio=min_ej,
                sueno_asleep_horas=sleep_h,
                respiraciones_por_min_media=_f(r.get("averageRespirationValue")),
                hrv_sdnn_ms_media=_f(r.get("lastNight5MinHighHRV")),
            ))
        return records

    def _from_all_metrics(self, data: dict) -> List[NormalizedRecord]:
        mm = data.get("allMetrics", {}).get("metricsMap", {})

        def extract(key):
            entries = mm.get(key, [])
            return {e["calendarDate"]: e.get("value") for e in entries if "calendarDate" in e}

        hr_map    = extract("WELLNESS_RESTING_HEART_RATE")
        steps_map = extract("WELLNESS_TOTAL_STEPS")
        sleep_map = extract("WELLNESS_TOTAL_SLEEP_TIME_SECONDS")
        ex_map    = extract("WELLNESS_MODERATE_INTENSITY_MINUTES")

        fechas = sorted(set(hr_map) | set(steps_map) | set(sleep_map))
        records = []
        for fecha in fechas:
            sleep_sec = _f(sleep_map.get(fecha))
            sleep_h   = round(sleep_sec / 3600, 2) if sleep_sec else None
            records.append(NormalizedRecord(
                fecha=fecha,
                pulso_reposo_bpm_media=_f(hr_map.get(fecha)),
                pasos=_f(steps_map.get(fecha)),
                min_ejercicio=_f(ex_map.get(fecha)),
                sueno_asleep_horas=sleep_h,
                respiraciones_por_min_media=None,
                hrv_sdnn_ms_media=None,
            ))
        return records


def _f(v: Any):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None
