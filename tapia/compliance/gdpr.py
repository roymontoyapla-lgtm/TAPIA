# -*- coding: utf-8 -*-
"""
Funciones de cumplimiento RGPD para TAPIA.

Incluye:
  - Registro de consentimiento informado por paciente
  - Exportacion de todos los datos de un paciente (portabilidad)
  - Derecho al olvido (borrado completo + registro en auditoria)
  - Listado de datos almacenados para transparencia
"""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from .audit import log, Action
from ..db.crypto import decrypt

logger = logging.getLogger(__name__)

_DB_PATH = Path(__file__).resolve().parent.parent / "tapia_history.db"


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


# ---------------------------------------------------------------------------
# Tabla de consentimientos
# ---------------------------------------------------------------------------

def init_consent_table() -> None:
    """Crea la tabla de consentimientos si no existe. Idempotente."""
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS consents (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_id  INTEGER NOT NULL,
                granted     INTEGER NOT NULL DEFAULT 1,  -- 1=otorgado, 0=revocado
                timestamp   TEXT    NOT NULL,
                ip_hash     TEXT,
                notes       TEXT
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_consents_patient "
            "ON consents(patient_id)"
        )
    logger.debug("Tabla consents inicializada.")


def record_consent(
    patient_id: int,
    granted: bool = True,
    notes: str = "",
) -> None:
    """Registra el consentimiento (o su revocacion) de un paciente."""
    now = datetime.now().isoformat()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO consents (patient_id, granted, timestamp, notes) VALUES (?,?,?,?)",
            (patient_id, 1 if granted else 0, now, notes),
        )
    action = Action.CONSENT_GRANTED if granted else Action.CONSENT_REVOKED
    log(action, patient_id=patient_id, details=notes)
    logger.info("Consentimiento %s para patient_id=%d", "otorgado" if granted else "revocado", patient_id)


def get_consent_status(patient_id: int) -> Optional[Dict[str, Any]]:
    """
    Devuelve el ultimo estado de consentimiento del paciente,
    o None si no hay ningun registro.
    """
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM consents WHERE patient_id = ? ORDER BY timestamp DESC LIMIT 1",
            (patient_id,),
        ).fetchone()
    return dict(row) if row else None


def has_valid_consent(patient_id: int) -> bool:
    """True si el paciente tiene consentimiento vigente (ultimo registro = otorgado)."""
    status = get_consent_status(patient_id)
    return bool(status and status["granted"])


# ---------------------------------------------------------------------------
# Portabilidad de datos (exportacion)
# ---------------------------------------------------------------------------

def export_patient_data(patient_id: int, patient_name: str) -> str:
    """
    Exporta todos los datos de un paciente en formato JSON legible.
    Devuelve el JSON como string.
    """
    with _connect() as conn:
        # Datos del paciente
        patient_row = conn.execute(
            "SELECT * FROM patients WHERE id = ?", (patient_id,)
        ).fetchone()

        # Triajes
        triage_rows = conn.execute(
            "SELECT * FROM triages WHERE patient_id = ? ORDER BY created_at",
            (patient_id,),
        ).fetchall()

        # Wearable
        wearable_rows = conn.execute(
            "SELECT fecha, hr_resting, steps, exercise_min, sleep_h, resp_rate, hrv, source "
            "FROM wearable_data WHERE patient_id = ? ORDER BY fecha",
            (patient_id,),
        ).fetchall()

        # Consentimientos
        consent_rows = conn.execute(
            "SELECT timestamp, granted, notes FROM consents WHERE patient_id = ? ORDER BY timestamp",
            (patient_id,),
        ).fetchall()

    def safe_dec(v):
        try: return decrypt(v)
        except: return v

    export = {
        "tapia_export": {
            "generated_at":   datetime.now().isoformat(timespec="seconds"),
            "patient": {
                "id":         patient_id,
                "name":       patient_name,
                "age":        patient_row["age"]   if patient_row else None,
                "sex":        patient_row["sex"]   if patient_row else None,
                "created_at": patient_row["created_at"] if patient_row else None,
            },
            "triages": [
                {
                    "id":           r["id"],
                    "created_at":   r["created_at"],
                    "final_bucket": r["final_bucket"],
                    "local_score":  r["local_score"],
                    "ai_model":     r["ai_model"],
                    "rec":          r["rec"],
                    "report":       safe_dec(r["report_text"]),
                }
                for r in triage_rows
            ],
            "wearable_days": [dict(r) for r in wearable_rows],
            "consents": [dict(r) for r in consent_rows],
        }
    }

    json_str = json.dumps(export, ensure_ascii=False, indent=2)
    log(Action.DATA_EXPORTED, patient_id=patient_id,
        details=f"{len(triage_rows)} triajes, {len(wearable_rows)} dias wearable")
    return json_str


# ---------------------------------------------------------------------------
# Derecho al olvido
# ---------------------------------------------------------------------------

def erase_patient(patient_id: int, patient_name: str) -> Dict[str, int]:
    """
    Elimina TODOS los datos de un paciente (derecho al olvido RGPD art. 17).
    Queda un registro en la auditoria con el hecho del borrado (sin datos personales).
    """
    with _connect() as conn:
        t = conn.execute(
            "DELETE FROM triages       WHERE patient_id = ?", (patient_id,)
        ).rowcount
        w = conn.execute(
            "DELETE FROM wearable_data WHERE patient_id = ?", (patient_id,)
        ).rowcount
        c = conn.execute(
            "DELETE FROM consents      WHERE patient_id = ?", (patient_id,)
        ).rowcount
        conn.execute(
            "DELETE FROM patients      WHERE id = ?", (patient_id,)
        )

    # Registrar el borrado en auditoria (sin datos personales del paciente)
    log(
        Action.PATIENT_DELETED,
        patient_id=None,  # ya no existe, no vincular
        details=f"Derecho al olvido: {t} triajes, {w} dias wearable, {c} consentimientos eliminados",
    )
    logger.info(
        "Paciente id=%d eliminado por derecho al olvido: %d triajes, %d dias wearable",
        patient_id, t, w,
    )
    return {"triajes": t, "wearable_days": w, "consentimientos": c}


# ---------------------------------------------------------------------------
# Inventario de datos (transparencia)
# ---------------------------------------------------------------------------

def data_inventory(patient_id: int) -> Dict[str, Any]:
    """
    Devuelve un inventario de los datos almacenados de un paciente
    para mostrar en la UI (transparencia RGPD art. 13-14).
    """
    with _connect() as conn:
        n_triages = conn.execute(
            "SELECT COUNT(*) FROM triages WHERE patient_id = ?", (patient_id,)
        ).fetchone()[0]
        n_wearable = conn.execute(
            "SELECT COUNT(*) FROM wearable_data WHERE patient_id = ?", (patient_id,)
        ).fetchone()[0]
        n_consents = conn.execute(
            "SELECT COUNT(*) FROM consents WHERE patient_id = ?", (patient_id,)
        ).fetchone()[0]
        first_w = conn.execute(
            "SELECT MIN(fecha) FROM wearable_data WHERE patient_id = ?", (patient_id,)
        ).fetchone()[0]
        last_w = conn.execute(
            "SELECT MAX(fecha) FROM wearable_data WHERE patient_id = ?", (patient_id,)
        ).fetchone()[0]

    return {
        "triajes":         n_triages,
        "dias_wearable":   n_wearable,
        "consentimientos": n_consents,
        "wearable_desde":  first_w or "N/D",
        "wearable_hasta":  last_w  or "N/D",
        "datos_cifrados":  True,
    }
