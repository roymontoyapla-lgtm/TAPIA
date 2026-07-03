# -*- coding: utf-8 -*-
"""
Adaptador para exportaciones de Withings (Nokia Health).

Withings exporta datos en CSV o JSON. El formato JSON tipico es:

{
  "status": 0,
  "body": {
    "series": [
      {
        "date": 1709251200,
        "heart_rate": {"resting": 62},
        "steps": 7500,
        "sleep": {"total": 25200},
        "calories_active": 350
      }
    ]
  }
}

O en formato simplificado de lista:
[
  {
    "date": "2024-03-01",
    "heart_rate_resting": 62,
    "steps": 7500,
    "sleep_duration": 25200,
    "active_calories": 350
  }
]
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, List

from .base import BaseAdapter, NormalizedRecord


class WithingsAdapter(BaseAdapter):
    NAME = "withings"
    DESCRIPTION = "Exportacion Withings"

    def can_handle(self, data: Any) -> bool:
        # Formato API con body.series
        if isinstance(data, dict) and "body" in data:
            body = data.get("body", {})
            return "series" in body
        # Formato lista simplificada
        if isinstance(data, list) and data:
            first = data[0]
            return isinstance(first, dict) and any(
                k in first for k in ["heart_rate_resting", "sleep_duration"]
            )
        return False

    def normalize(self, data: Any) -> List[NormalizedRecord]:
        if isinstance(data, dict) and "body" in data:
            series = data["body"].get("series", [])
            return self._from_api(series)
        if isinstance(data, list):
            return self._from_list(data)
        return []

    def _from_api(self, series: list) -> List[NormalizedRecord]:
        records = []
        for r in series:
            if not isinstance(r, dict):
                continue
            # Fecha puede ser timestamp Unix o string
            fecha = _parse_date(r.get("date", ""))
            if not fecha:
                continue

            hr_obj = r.get("heart_rate", {})
            hr = _f(hr_obj.get("resting") if isinstance(hr_obj, dict) else None)

            sleep_obj = r.get("sleep", {})
            sleep_sec = _f(sleep_obj.get("total") if isinstance(sleep_obj, dict) else None)
            sleep_h   = round(sleep_sec / 3600, 2) if sleep_sec else None

            records.append(NormalizedRecord(
                fecha=fecha,
                pulso_reposo_bpm_media=hr,
                pasos=_f(r.get("steps")),
                min_ejercicio=None,
                sueno_asleep_horas=sleep_h,
                respiraciones_por_min_media=_f(r.get("breathing_disturbances_intensity")),
                hrv_sdnn_ms_media=None,
            ))
        return records

    def _from_list(self, data: list) -> List[NormalizedRecord]:
        records = []
        for r in data:
            if not isinstance(r, dict):
                continue
            fecha = _parse_date(r.get("date", ""))
            if not fecha:
                continue

            sleep_sec = _f(r.get("sleep_duration"))
            sleep_h   = round(sleep_sec / 3600, 2) if sleep_sec else None

            records.append(NormalizedRecord(
                fecha=fecha,
                pulso_reposo_bpm_media=_f(r.get("heart_rate_resting")),
                pasos=_f(r.get("steps")),
                min_ejercicio=None,
                sueno_asleep_horas=sleep_h,
                respiraciones_por_min_media=None,
                hrv_sdnn_ms_media=None,
            ))
        return records


def _parse_date(v: Any) -> str:
    if isinstance(v, (int, float)):
        try:
            return datetime.fromtimestamp(v).strftime("%Y-%m-%d")
        except Exception:
            return ""
    if isinstance(v, str):
        return v[:10]
    return ""


def _f(v: Any):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None
