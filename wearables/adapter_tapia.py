# -*- coding: utf-8 -*-
"""Adaptador para el formato nativo de TAPIA."""

from __future__ import annotations

from typing import Any, List

from .base import BaseAdapter, NormalizedRecord


class TapiaAdapter(BaseAdapter):
    NAME = "tapia"
    DESCRIPTION = "Formato nativo TAPIA"

    def can_handle(self, data: Any) -> bool:
        if not isinstance(data, list) or not data:
            return False
        first = data[0] if isinstance(data, list) else {}
        return isinstance(first, dict) and "fecha" in first

    def normalize(self, data: Any) -> List[NormalizedRecord]:
        records = []
        for r in data:
            if not isinstance(r, dict) or "fecha" not in r:
                continue
            records.append(NormalizedRecord(
                fecha=str(r.get("fecha", "")),
                pulso_reposo_bpm_media=_f(r.get("pulso_reposo_bpm_media")),
                pasos=_f(r.get("pasos")),
                min_ejercicio=_f(r.get("min_ejercicio")),
                sueno_asleep_horas=_f(r.get("sueno_asleep_horas")),
                respiraciones_por_min_media=_f(r.get("respiraciones_por_min_media")),
                hrv_sdnn_ms_media=_f(r.get("hrv_sdnn_ms_media")),
            ))
        return records


def _f(v: Any):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None
