"""Carga, filtrado y resumen de datos del wearable."""

import json
import logging
from datetime import datetime, timedelta
from statistics import mean
from typing import Any, Dict, List, Optional

from .config import cfg
from .models import WearableSummary

logger = logging.getLogger(__name__)

F = cfg.wearable.fields  # alias corto


# ---------------------------------------------------------------------------
# Utilidades de bajo nivel
# ---------------------------------------------------------------------------

def to_float(x: Any) -> Optional[float]:
    if isinstance(x, (int, float)):
        return float(x)
    return None


def mean_or_none(vals: List[Optional[float]]) -> Optional[float]:
    clean = [v for v in vals if isinstance(v, (int, float))]
    return round(mean(clean), 2) if clean else None


def count_days(vals: List[Optional[float]], predicate) -> int:
    return sum(1 for v in vals if isinstance(v, (int, float)) and predicate(v))


def parse_date(s: Any) -> Optional[datetime]:
    if not isinstance(s, str):
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Carga y filtrado
# ---------------------------------------------------------------------------

def load_json(path: str) -> List[Dict[str, Any]]:
    """Lee un fichero JSON y devuelve una lista de registros dict."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("El JSON no es una lista de registros.")
    records = [r for r in data if isinstance(r, dict)]
    logger.debug("Cargados %d registros desde %s", len(records), path)
    return records


def filter_by_days(records: List[Dict[str, Any]], days: int) -> List[Dict[str, Any]]:
    """Devuelve solo los registros de los últimos `days` días."""
    date_field = cfg.wearable.date_field
    dated = [(parse_date(r.get(date_field)), r) for r in records]
    dated = [(d, r) for d, r in dated if d is not None]
    if not dated:
        return []
    max_d  = max(d for d, _ in dated)
    cutoff = max_d - timedelta(days=days)
    return [r for d, r in dated if d >= cutoff]


def date_range_str(records: List[Dict[str, Any]]) -> str:
    date_field = cfg.wearable.date_field
    ds = [parse_date(r.get(date_field)) for r in records]
    ds = [d for d in ds if d is not None]
    if not ds:
        return "N/D"
    return f"{min(ds).date().isoformat()} a {max(ds).date().isoformat()}"


# ---------------------------------------------------------------------------
# Resumen estadístico
# ---------------------------------------------------------------------------

def summarize(records: List[Dict[str, Any]]) -> WearableSummary:
    """Calcula métricas agregadas a partir de una lista de registros."""
    thr   = cfg.thresholds
    sleep = [to_float(r.get(F["sleep_h"]))      for r in records]
    steps = [to_float(r.get(F["steps"]))         for r in records]
    hr    = [to_float(r.get(F["resting_hr"]))    for r in records]
    exmin = [to_float(r.get(F["exercise_min"]))  for r in records]
    resp  = [to_float(r.get(F["resp_rate"]))     for r in records]
    hrv   = [to_float(r.get(F["hrv"]))           for r in records]

    return WearableSummary(
        days=len(records),
        range=date_range_str(records),
        avg_resting_hr=mean_or_none(hr),
        avg_steps=mean_or_none(steps),
        avg_exercise_min=mean_or_none(exmin),
        avg_sleep_h=mean_or_none(sleep),
        avg_resp=mean_or_none(resp),
        avg_hrv=mean_or_none(hrv),
        low_sleep_days=count_days(
            sleep, lambda v: v < thr.sleep.low_hours
        ),
        very_low_activity_days=count_days(
            steps, lambda v: v < thr.activity.very_low_steps
        ),
        high_resting_hr_days=count_days(
            hr, lambda v: v >= thr.hr.high_resting_bpm
        ),
    )
