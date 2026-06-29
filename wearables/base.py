# -*- coding: utf-8 -*-
"""
Formato normalizado de registro y clase base para adaptadores de wearable.
Todos los adaptadores convierten su formato nativo a una lista de NormalizedRecord.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class NormalizedRecord:
    """Un dia de datos de wearable en formato estandar interno de TAPIA."""
    fecha:                str            # "YYYY-MM-DD"
    pulso_reposo_bpm_media:   Optional[float]
    pasos:                    Optional[float]
    min_ejercicio:            Optional[float]
    sueno_asleep_horas:       Optional[float]
    respiraciones_por_min_media: Optional[float]
    hrv_sdnn_ms_media:        Optional[float]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fecha":                        self.fecha,
            "pulso_reposo_bpm_media":       self.pulso_reposo_bpm_media,
            "pasos":                        self.pasos,
            "min_ejercicio":                self.min_ejercicio,
            "sueno_asleep_horas":           self.sueno_asleep_horas,
            "respiraciones_por_min_media":  self.respiraciones_por_min_media,
            "hrv_sdnn_ms_media":            self.hrv_sdnn_ms_media,
        }


class BaseAdapter:
    """Clase base para todos los adaptadores de wearable."""

    NAME = "generico"
    DESCRIPTION = "Formato generico"

    def can_handle(self, data: Any) -> bool:
        """Devuelve True si este adaptador puede procesar los datos."""
        raise NotImplementedError

    def normalize(self, data: Any) -> List[NormalizedRecord]:
        """Convierte los datos al formato normalizado de TAPIA."""
        raise NotImplementedError
