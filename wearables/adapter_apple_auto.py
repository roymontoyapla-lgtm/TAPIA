# -*- coding: utf-8 -*-
"""
Adaptador para el JSON que genera Health Auto Export (Apple Health).

Es el formato que produce la app del iPhone al exportar automaticamente a
Dropbox, Google Drive o a un endpoint REST. No se parece al export.xml ni
al JSON plano que entiende AppleHealthAdapter: va agrupado por metrica.

    {
      "data": {
        "metrics": [
          {"name": "step_count", "units": "count",
           "data": [{"date": "2026-09-01 00:00:00 +0200", "qty": 7500}]},
          {"name": "resting_heart_rate", "units": "count/min",
           "data": [{"date": "2026-09-01 00:00:00 +0200", "Avg": 58}]},
          {"name": "sleep_analysis", "units": "hr",
           "data": [{"date": "2026-09-01 00:00:00 +0200", "asleep": 7.2}]}
        ],
        "workouts": []
      }
    }

El formato varia entre versiones de la app y segun la agregacion elegida,
asi que el adaptador es deliberadamente tolerante:

  - Acepta el payload envuelto en "data" o sin envolver, y una lista de
    payloads (la app parte los envios grandes en varias peticiones).
  - Acepta varios puntos por dia: los suma (pasos, ejercicio, sueno) o
    promedia (frecuencia cardiaca, HRV, respiraciones) segun la metrica.
  - Acepta el valor en "qty", "Avg" o los campos de sueno, y convierte
    las unidades de minutos a horas cuando hace falta.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Dict, List, Optional

from .base import BaseAdapter, NormalizedRecord

logger = logging.getLogger(__name__)

# Nombre de metrica de Health Auto Export -> campo interno de TAPIA.
# Se admiten alias porque la app ha cambiado algunos nombres entre versiones.
_METRIC_MAP: Dict[str, str] = {
    "resting_heart_rate":            "hr",
    "heart_rate_resting":            "hr",
    "step_count":                    "steps",
    "steps":                         "steps",
    "apple_exercise_time":           "exercise",
    "exercise_time":                 "exercise",
    "sleep_analysis":                "sleep",
    "respiratory_rate":              "resp",
    "heart_rate_variability":        "hrv",
    "heart_rate_variability_sdnn":   "hrv",
    "hrv_sdnn":                      "hrv",
}

# Metricas que se acumulan a lo largo del dia frente a las que se promedian
_SUM_FIELDS  = {"steps", "exercise", "sleep"}
_MEAN_FIELDS = {"hr", "resp", "hrv"}

# Campos de sueno por orden de preferencia (la app expone varios)
_SLEEP_KEYS = ("asleep", "totalSleep", "total_sleep", "value", "qty")
_SLEEP_PHASES = ("core", "deep", "rem")


class AppleAutoExportAdapter(BaseAdapter):
    NAME = "apple_auto_export"
    DESCRIPTION = "Apple Health via Health Auto Export (JSON)"

    def can_handle(self, data: Any) -> bool:
        return _extract_metrics(data) is not None

    def normalize(self, data: Any) -> List[NormalizedRecord]:
        metrics = _extract_metrics(data)
        if not metrics:
            return []

        # fecha -> campo -> lista de valores del dia
        por_dia: Dict[str, Dict[str, List[float]]] = defaultdict(lambda: defaultdict(list))

        for metric in metrics:
            if not isinstance(metric, dict):
                continue
            campo = _METRIC_MAP.get(str(metric.get("name", "")).strip().lower())
            if campo is None:
                continue

            units  = str(metric.get("units", "")).strip().lower()
            puntos = metric.get("data") or []
            if not isinstance(puntos, list):
                continue

            for punto in puntos:
                if not isinstance(punto, dict):
                    continue
                fecha = _parse_fecha(punto.get("date"))
                if not fecha:
                    continue
                valor = _sleep_hours(punto, units) if campo == "sleep" else _value(punto)
                if valor is None:
                    continue
                if campo == "exercise" and units in ("hr", "h", "hour", "hours"):
                    valor *= 60          # el ejercicio se guarda en minutos
                por_dia[fecha][campo].append(valor)

        registros: List[NormalizedRecord] = []
        for fecha in sorted(por_dia):
            campos = por_dia[fecha]
            registros.append(NormalizedRecord(
                fecha=fecha,
                pulso_reposo_bpm_media=_agg(campos.get("hr"),       "hr"),
                pasos=_agg(campos.get("steps"),                     "steps"),
                min_ejercicio=_agg(campos.get("exercise"),          "exercise"),
                sueno_asleep_horas=_agg(campos.get("sleep"),        "sleep"),
                respiraciones_por_min_media=_agg(campos.get("resp"), "resp"),
                hrv_sdnn_ms_media=_agg(campos.get("hrv"),           "hrv"),
            ))

        logger.info("Health Auto Export: %d dias normalizados", len(registros))
        return registros


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_metrics(data: Any) -> Optional[List[Any]]:
    """
    Localiza la lista de metricas admitiendo las variantes del formato:
    envuelto en "data", sin envolver, o una lista de payloads (envios por lotes).
    Devuelve None si los datos no son de Health Auto Export.
    """
    if isinstance(data, list):
        metricas: List[Any] = []
        for item in data:
            parcial = _extract_metrics(item)
            if parcial:
                metricas.extend(parcial)
        return metricas or None

    if not isinstance(data, dict):
        return None

    contenedor = data.get("data") if isinstance(data.get("data"), dict) else data
    metricas = contenedor.get("metrics")
    if not isinstance(metricas, list) or not metricas:
        return None

    # Debe parecerse a una metrica: {"name": ..., "data": [...]}
    primera = metricas[0]
    if not isinstance(primera, dict) or "name" not in primera:
        return None
    return metricas


def _parse_fecha(valor: Any) -> Optional[str]:
    """'2026-09-01 00:00:00 +0200' -> '2026-09-01'."""
    if not valor:
        return None
    texto = str(valor).strip()
    if len(texto) < 10:
        return None
    fecha = texto[:10]
    return fecha if fecha[4] == "-" and fecha[7] == "-" else None


def _value(punto: Dict[str, Any]) -> Optional[float]:
    """Valor de un punto: 'qty' si existe, si no la media del rango."""
    for clave in ("qty", "Avg", "avg", "value"):
        if clave in punto:
            return _f(punto[clave])
    return None


def _sleep_hours(punto: Dict[str, Any], units: str) -> Optional[float]:
    """
    Horas de sueno de un punto. Prefiere el sueno real; si solo hay fases,
    las suma. Convierte de minutos o segundos a horas segun las unidades.
    """
    valor = None
    for clave in _SLEEP_KEYS:
        if punto.get(clave) is not None:
            valor = _f(punto[clave])
            if valor is not None:
                break

    if valor is None:
        fases = [_f(punto.get(f)) for f in _SLEEP_PHASES]
        fases = [v for v in fases if v is not None]
        if fases:
            valor = sum(fases)

    if valor is None:
        return None

    if units in ("min", "mins", "minutes"):
        valor /= 60
    elif units in ("s", "sec", "secs", "seconds"):
        valor /= 3600
    return valor


def _agg(valores: Optional[List[float]], campo: str) -> Optional[float]:
    """Suma o promedia los valores del dia segun la metrica."""
    if not valores:
        return None
    if campo in _SUM_FIELDS:
        total = sum(valores)
    elif campo in _MEAN_FIELDS:
        total = sum(valores) / len(valores)
    else:
        total = valores[-1]
    return round(total, 2)


def _f(valor: Any) -> Optional[float]:
    try:
        return float(valor) if valor is not None else None
    except (TypeError, ValueError):
        return None
