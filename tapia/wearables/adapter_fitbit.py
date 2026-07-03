# -*- coding: utf-8 -*-
"""
Adaptador para exportaciones de Fitbit.

Fitbit exporta los datos como una carpeta ZIP con multiples JSON.
Para TAPIA, el usuario debe exportar y combinar manualmente, o usar
el formato de actividad diaria que Fitbit genera en su API.

Formatos soportados:
  1. Lista de actividades diarias (activities-heart-YYYY-MM-DD.json)
  2. Resumen diario combinado (formato tipico de exportacion manual)

Ejemplo de estructura esperada:
[
  {
    "dateTime": "2024-03-01",
    "value": {
      "restingHeartRate": 62,
      "steps": 7500,
      "minutesAsleep": 420,
      "minutesFairlyActive": 30,
      "minutesVeryActive": 15
    }
  }
]
"""

from __future__ import annotations

from typing import Any, List

from .base import BaseAdapter, NormalizedRecord


class FitbitAdapter(BaseAdapter):
    NAME = "fitbit"
    DESCRIPTION = "Exportacion Fitbit"

    def can_handle(self, data: Any) -> bool:
        if not isinstance(data, list) or not data:
            return False
        first = data[0]
        if not isinstance(first, dict):
            return False
        # Fitbit usa "dateTime" en lugar de "fecha"
        return "dateTime" in first and "value" in first

    def normalize(self, data: Any) -> List[NormalizedRecord]:
        records = []
        for r in data:
            if not isinstance(r, dict):
                continue
            fecha = r.get("dateTime", "")
            val   = r.get("value", {}) if isinstance(r.get("value"), dict) else {}

            # Minutos de ejercicio = fairly + very active
            fairly = _f(val.get("minutesFairlyActive", 0)) or 0
            very   = _f(val.get("minutesVeryActive",   0)) or 0
            min_ej = fairly + very if (fairly + very) > 0 else None

            # Sueno en horas
            min_sleep = _f(val.get("minutesAsleep"))
            sleep_h   = round(min_sleep / 60, 2) if min_sleep is not None else None

            records.append(NormalizedRecord(
                fecha=str(fecha),
                pulso_reposo_bpm_media=_f(val.get("restingHeartRate")),
                pasos=_f(val.get("steps")),
                min_ejercicio=min_ej,
                sueno_asleep_horas=sleep_h,
                respiraciones_por_min_media=_f(val.get("breathingRate")),
                hrv_sdnn_ms_media=_f(val.get("hrv")),
            ))
        return records


def _f(v: Any):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None
