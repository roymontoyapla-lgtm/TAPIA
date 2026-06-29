"""
Gestión centralizada del estado de sesión de Streamlit.
Todos los módulos leen/escriben el estado a través de aquí.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

try:
    import streamlit as st
    _ST_OK = True
except ImportError:
    st = None   # type: ignore
    _ST_OK = False


@dataclass
class TriageRecord:
    """Un triaje completado guardado en el historial de sesión."""
    timestamp: str
    patient_name: str
    patient_age: int
    patient_sex: str
    local_bucket: str
    local_score: int
    final_bucket: str
    ai_bucket: str
    ai_model: str
    rec: str           # AP vs especialista
    spec: str
    report_text: str
    wearable_days: int


def _ss() -> Any:
    """Devuelve st.session_state o lanza error claro si Streamlit no está disponible."""
    if not _ST_OK:
        raise RuntimeError("Streamlit no está instalado.")
    return st.session_state


def init() -> None:
    """Inicializa las claves de sesión necesarias (idempotente)."""
    ss = _ss()
    defaults: Dict[str, Any] = {
        "history": [],
        "last_report": "",
        "last_record": None,
        "wearable_records": [],
    }
    for key, val in defaults.items():
        if key not in ss:
            ss[key] = val


def save_triage(record: TriageRecord) -> None:
    ss = _ss()
    ss.history.insert(0, record)
    ss.last_record = record
    ss.last_report = record.report_text


def get_history() -> List[TriageRecord]:
    return _ss().get("history", [])


def get_last_report() -> str:
    return _ss().get("last_report", "")


def get_wearable_records() -> List[Dict[str, Any]]:
    return _ss().get("wearable_records", [])


def set_wearable_records(records: List[Dict[str, Any]]) -> None:
    _ss().wearable_records = records


def clear_history() -> None:
    ss = _ss()
    ss.history = []
    ss.last_report = ""
    ss.last_record = None
    ss.wearable_records = []
