# -*- coding: utf-8 -*-
"""
Registro de auditoria inmutable para TAPIA.

Cada accion relevante (triaje, importacion, borrado, exportacion, consentimiento)
queda registrada en la tabla audit_log con timestamp, tipo de accion,
patient_id anonimizado y version del algoritmo.

La tabla es de solo insercion (no se permite UPDATE ni DELETE sobre ella)
para garantizar la trazabilidad ante cualquier revision clinica o legal.
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

logger = logging.getLogger(__name__)

_DB_PATH = Path(__file__).resolve().parent.parent / "tapia_history.db"

# Version del algoritmo de triaje (actualizar con cada cambio clinico relevante)
ALGORITHM_VERSION = "1.2.0"

# Tipos de accion auditados
class Action:
    TRIAGE_RUN       = "triage_run"
    WEARABLE_IMPORT  = "wearable_import"
    PATIENT_CREATED  = "patient_created"
    PATIENT_DELETED  = "patient_deleted"
    DATA_EXPORTED    = "data_exported"
    CONSENT_GRANTED  = "consent_granted"
    CONSENT_REVOKED  = "consent_revoked"
    REPORT_DOWNLOADED= "report_downloaded"
    DB_PURGE         = "db_purge"


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_audit_table() -> None:
    """Crea la tabla de auditoria si no existe. Idempotente."""
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp         TEXT    NOT NULL,
                action            TEXT    NOT NULL,
                patient_id        INTEGER,
                algorithm_version TEXT    NOT NULL,
                details           TEXT,
                final_bucket      TEXT,
                local_score       INTEGER,
                ai_model          TEXT,
                source            TEXT
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_timestamp "
            "ON audit_log(timestamp)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_action "
            "ON audit_log(action)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_patient "
            "ON audit_log(patient_id)"
        )
    logger.debug("Tabla audit_log inicializada.")


def log(
    action: str,
    patient_id: Optional[int] = None,
    details: str = "",
    final_bucket: Optional[str] = None,
    local_score: Optional[int] = None,
    ai_model: Optional[str] = None,
    source: Optional[str] = None,
) -> None:
    """Inserta un registro de auditoria. Nunca lanza excepcion al exterior."""
    try:
        now = datetime.now().isoformat(timespec="seconds")
        with _connect() as conn:
            conn.execute(
                """
                INSERT INTO audit_log
                  (timestamp, action, patient_id, algorithm_version,
                   details, final_bucket, local_score, ai_model, source)
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (now, action, patient_id, ALGORITHM_VERSION,
                 details, final_bucket, local_score, ai_model, source),
            )
        logger.debug("Auditoria: %s | patient_id=%s", action, patient_id)
    except Exception as e:
        logger.error("No se pudo registrar en auditoria: %s", e)


def get_log(
    limit: int = 200,
    action_filter: Optional[str] = None,
    patient_id_filter: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Devuelve entradas del log de auditoria."""
    with _connect() as conn:
        conditions = []
        params: List[Any] = []
        if action_filter:
            conditions.append("action = ?")
            params.append(action_filter)
        if patient_id_filter is not None:
            conditions.append("patient_id = ?")
            params.append(patient_id_filter)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(limit)
        rows = conn.execute(
            f"SELECT * FROM audit_log {where} ORDER BY timestamp DESC LIMIT ?",
            params,
        ).fetchall()
    return [dict(r) for r in rows]


def get_stats() -> Dict[str, Any]:
    """Estadisticas del log de auditoria."""
    with _connect() as conn:
        total = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
        by_action = dict(conn.execute(
            "SELECT action, COUNT(*) FROM audit_log GROUP BY action"
        ).fetchall())
        first = conn.execute(
            "SELECT MIN(timestamp) FROM audit_log"
        ).fetchone()[0]
        last = conn.execute(
            "SELECT MAX(timestamp) FROM audit_log"
        ).fetchone()[0]
    return {
        "total":     total,
        "by_action": by_action,
        "first":     first or "N/D",
        "last":      last  or "N/D",
    }
