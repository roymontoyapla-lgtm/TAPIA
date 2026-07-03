# -*- coding: utf-8 -*-
"""
Capa de persistencia SQLite para TAPIA.

Tablas:
  triages       -- historial de triajes (nombre e informe cifrados)
  patients      -- registro de pacientes (nombre cifrado, id interno)
  wearable_data -- registros diarios del wearable por paciente

El wearable se guarda de forma acumulativa: cada importacion solo
inserta los dias nuevos (importacion incremental sin duplicados).
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from .crypto import decrypt, encrypt

logger = logging.getLogger(__name__)

_DB_PATH = Path(__file__).resolve().parent.parent / "tapia_history.db"


# ---------------------------------------------------------------------------
# Conexion
# ---------------------------------------------------------------------------

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
# Esquema
# ---------------------------------------------------------------------------

def init_db() -> None:
    """Crea todas las tablas e indices si no existen. Idempotente."""
    with _connect() as conn:

        # Tabla de pacientes
        conn.execute("""
            CREATE TABLE IF NOT EXISTS patients (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT    NOT NULL,
                name       TEXT    NOT NULL,   -- cifrado
                age        INTEGER NOT NULL,
                sex        TEXT    NOT NULL
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_patients_created ON patients(created_at)"
        )

        # Tabla de triajes
        conn.execute("""
            CREATE TABLE IF NOT EXISTS triages (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at    TEXT    NOT NULL,
                patient_id    INTEGER REFERENCES patients(id),
                patient_name  TEXT    NOT NULL,   -- cifrado (redundante para busqueda rapida)
                patient_age   INTEGER NOT NULL,
                patient_sex   TEXT    NOT NULL,
                local_bucket  TEXT    NOT NULL,
                local_score   INTEGER NOT NULL,
                final_bucket  TEXT    NOT NULL,
                ai_bucket     TEXT    NOT NULL,
                ai_model      TEXT,
                rec           TEXT,
                spec          TEXT,
                wearable_days INTEGER,
                report_text   TEXT    NOT NULL    -- cifrado
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_triages_created    ON triages(created_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_triages_bucket     ON triages(final_bucket)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_triages_patient_id ON triages(patient_id)"
        )

        # Tabla de datos wearable acumulativos
        conn.execute("""
            CREATE TABLE IF NOT EXISTS wearable_data (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_id    INTEGER NOT NULL REFERENCES patients(id),
                fecha         TEXT    NOT NULL,   -- YYYY-MM-DD
                hr_resting    REAL,
                steps         REAL,
                exercise_min  REAL,
                sleep_h       REAL,
                resp_rate     REAL,
                hrv           REAL,
                source        TEXT,               -- nombre del adaptador (tapia, fitbit, ...)
                imported_at   TEXT    NOT NULL,
                UNIQUE(patient_id, fecha)         -- sin duplicados por paciente y dia
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_wearable_patient_fecha "
            "ON wearable_data(patient_id, fecha)"
        )

        # Tabla de analisis clinicos
        conn.execute("""
            CREATE TABLE IF NOT EXISTS lab_results (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_id   INTEGER NOT NULL REFERENCES patients(id),
                fecha        TEXT,
                laboratorio  TEXT,
                raw_json     TEXT NOT NULL,
                score_lab    INTEGER DEFAULT 0,
                imported_at  TEXT NOT NULL,
                notes        TEXT
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_lab_patient "
            "ON lab_results(patient_id)"
        )

    logger.debug("Base de datos inicializada en %s", _DB_PATH)


# ---------------------------------------------------------------------------
# Pacientes
# ---------------------------------------------------------------------------

def update_patient_info(patient_id: int, age: int, sex: str) -> None:
    """
    Actualiza edad y sexo de un paciente existente si los valores nuevos
    son validos (age>0, sex no vacio). Se llama en cada triaje para
    mantener el registro maestro sincronizado con el formulario.
    """
    if not age and not sex:
        return
    with _connect() as conn:
        row = conn.execute(
            "SELECT age, sex FROM patients WHERE id = ?", (patient_id,)
        ).fetchone()
        if row is None:
            return
        new_age = age if age else row["age"]
        new_sex = sex if sex else row["sex"]
        if new_age != row["age"] or new_sex != row["sex"]:
            conn.execute(
                "UPDATE patients SET age = ?, sex = ? WHERE id = ?",
                (new_age, new_sex, patient_id),
            )
            logger.debug("Paciente id=%d sincronizado: age=%s sex=%s", patient_id, new_age, new_sex)


def get_or_create_patient(name: str, age: int, sex: str) -> int:
    """
    Busca un paciente por nombre cifrado o lo crea si no existe.
    Devuelve el patient_id.

    Si el paciente ya existe pero tiene edad/sexo vacios (por ejemplo por
    un registro antiguo incompleto) y ahora se proporcionan valores validos,
    se actualiza el registro para completarlo (auto-reparacion).

    Nota: la busqueda descifra todos los nombres (O(n) sobre pacientes).
    """
    with _connect() as conn:
        rows = conn.execute("SELECT id, name, age, sex FROM patients").fetchall()
        for row in rows:
            try:
                if decrypt(row["name"]).lower() == name.lower():
                    pid = row["id"]
                    # Auto-reparacion: completar edad/sexo si faltaban
                    needs_age = (not row["age"]) and age
                    needs_sex = (not row["sex"]) and sex
                    if needs_age or needs_sex:
                        conn.execute(
                            "UPDATE patients SET age = ?, sex = ? WHERE id = ?",
                            (age if age else row["age"], sex if sex else row["sex"], pid),
                        )
                        logger.info("Paciente id=%d actualizado con edad/sexo faltantes.", pid)
                    return pid
            except Exception:
                continue

        # Crear nuevo paciente
        now = datetime.now().isoformat(timespec="seconds")
        cur = conn.execute(
            "INSERT INTO patients (created_at, name, age, sex) VALUES (?,?,?,?)",
            (now, encrypt(name), age, sex),
        )
        logger.debug("Nuevo paciente creado con id=%d", cur.lastrowid)
        return cur.lastrowid


def list_patients() -> List[Dict[str, Any]]:
    """Devuelve todos los pacientes descifrados."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, created_at, name, age, sex FROM patients ORDER BY created_at DESC"
        ).fetchall()
    result = []
    for r in rows:
        result.append({
            "id":         r["id"],
            "created_at": r["created_at"],
            "name":       _safe_decrypt(r["name"]),
            "age":        r["age"],
            "sex":        r["sex"],
        })
    return result


# ---------------------------------------------------------------------------
# Wearable acumulativo
# ---------------------------------------------------------------------------

def import_wearable_records(
    patient_id: int,
    records: List[Dict[str, Any]],
    source: str = "tapia",
) -> Dict[str, int]:
    """
    Importa registros diarios del wearable para un paciente.
    Usa INSERT OR IGNORE para evitar duplicados (mismo patient_id + fecha).
    Devuelve {"inserted": N, "skipped": N}.
    """
    now = datetime.now().isoformat(timespec="seconds")
    inserted = 0
    skipped  = 0

    with _connect() as conn:
        for r in records:
            fecha = r.get("fecha", "")
            if not fecha:
                skipped += 1
                continue
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO wearable_data
                  (patient_id, fecha, hr_resting, steps, exercise_min,
                   sleep_h, resp_rate, hrv, source, imported_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    patient_id,
                    fecha,
                    r.get("pulso_reposo_bpm_media"),
                    r.get("pasos"),
                    r.get("min_ejercicio"),
                    r.get("sueno_asleep_horas"),
                    r.get("respiraciones_por_min_media"),
                    r.get("hrv_sdnn_ms_media"),
                    source,
                    now,
                ),
            )
            if cur.rowcount > 0:
                inserted += 1
            else:
                skipped += 1

    logger.info(
        "Wearable importado para patient_id=%d: %d nuevos, %d duplicados omitidos",
        patient_id, inserted, skipped,
    )
    return {"inserted": inserted, "skipped": skipped}


def get_wearable_history(
    patient_id: int,
    days: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Devuelve los registros wearable de un paciente en formato dict
    compatible con core.wearable.summarize().
    Si `days` es None devuelve todo el historial.
    """
    with _connect() as conn:
        if days is not None:
            rows = conn.execute(
                """
                SELECT * FROM wearable_data
                WHERE patient_id = ?
                  AND fecha >= date('now', ? || ' days')
                ORDER BY fecha ASC
                """,
                (patient_id, f"-{days}"),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM wearable_data WHERE patient_id = ? ORDER BY fecha ASC",
                (patient_id,),
            ).fetchall()

    return [_wearable_row_to_dict(r) for r in rows]


def get_wearable_stats(patient_id: int) -> Dict[str, Any]:
    """Estadisticas del historial wearable de un paciente."""
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT
                COUNT(*)      AS total_days,
                MIN(fecha)    AS first_date,
                MAX(fecha)    AS last_date,
                MAX(imported_at) AS last_import,
                COUNT(DISTINCT source) AS sources
            FROM wearable_data
            WHERE patient_id = ?
            """,
            (patient_id,),
        ).fetchone()
    return {
        "total_days":  row["total_days"],
        "first_date":  row["first_date"] or "N/D",
        "last_date":   row["last_date"]  or "N/D",
        "last_import": row["last_import"] or "N/D",
        "sources":     row["sources"],
    }


def _wearable_row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    """Convierte una fila de wearable_data al formato que usa core.wearable."""
    return {
        "fecha":                       row["fecha"],
        "pulso_reposo_bpm_media":      row["hr_resting"],
        "pasos":                       row["steps"],
        "min_ejercicio":               row["exercise_min"],
        "sueno_asleep_horas":          row["sleep_h"],
        "respiraciones_por_min_media": row["resp_rate"],
        "hrv_sdnn_ms_media":           row["hrv"],
    }


# ---------------------------------------------------------------------------
# Triajes
# ---------------------------------------------------------------------------

def save_triage(
    patient_name:  str,
    patient_age:   int,
    patient_sex:   str,
    local_bucket:  str,
    local_score:   int,
    final_bucket:  str,
    ai_bucket:     str,
    ai_model:      str,
    rec:           str,
    spec:          str,
    wearable_days: int,
    report_text:   str,
    patient_id:    Optional[int] = None,
) -> int:
    now = datetime.now().isoformat(timespec="seconds")
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO triages
              (created_at, patient_id, patient_name, patient_age, patient_sex,
               local_bucket, local_score, final_bucket, ai_bucket,
               ai_model, rec, spec, wearable_days, report_text)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                now, patient_id,
                encrypt(patient_name), patient_age, patient_sex,
                local_bucket, local_score, final_bucket, ai_bucket,
                ai_model, rec, spec, wearable_days,
                encrypt(report_text),
            ),
        )
    logger.debug("Triaje guardado con id=%d", cur.lastrowid)
    return cur.lastrowid


class TriageRow:
    def __init__(self, row: sqlite3.Row) -> None:
        self.id:            int = row["id"]
        self.created_at:    str = row["created_at"]
        self.patient_id:    int = row["patient_id"] or 0
        self.patient_name:  str = _safe_decrypt(row["patient_name"])
        self.patient_age:   int = row["patient_age"]
        self.patient_sex:   str = row["patient_sex"]
        self.local_bucket:  str = row["local_bucket"]
        self.local_score:   int = row["local_score"]
        self.final_bucket:  str = row["final_bucket"]
        self.ai_bucket:     str = row["ai_bucket"]
        self.ai_model:      str = row["ai_model"] or ""
        self.rec:           str = row["rec"] or ""
        self.spec:          str = row["spec"] or ""
        self.wearable_days: int = row["wearable_days"] or 0
        self.report_text:   str = _safe_decrypt(row["report_text"])


def get_all(limit: int = 200) -> List[TriageRow]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM triages ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [TriageRow(r) for r in rows]


def get_by_id(triage_id: int) -> Optional[TriageRow]:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM triages WHERE id = ?", (triage_id,)
        ).fetchone()
    return TriageRow(row) if row else None


def get_by_patient(patient_id: int) -> List[TriageRow]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM triages WHERE patient_id = ? ORDER BY created_at DESC",
            (patient_id,),
        ).fetchall()
    return [TriageRow(r) for r in rows]


def search_by_name(fragment: str, limit: int = 50) -> List[TriageRow]:
    rows = get_all(limit=500)
    fragment_lower = fragment.lower()
    return [r for r in rows if fragment_lower in r.patient_name.lower()][:limit]


def get_stats() -> Dict[str, Any]:
    with _connect() as conn:
        total    = conn.execute("SELECT COUNT(*) FROM triages").fetchone()[0]
        by_bucket = dict(conn.execute(
            "SELECT final_bucket, COUNT(*) FROM triages GROUP BY final_bucket"
        ).fetchall())
        avg_score = conn.execute(
            "SELECT ROUND(AVG(local_score),1) FROM triages"
        ).fetchone()[0]
        n_patients = conn.execute("SELECT COUNT(*) FROM patients").fetchone()[0]
        total_wearable_days = conn.execute(
            "SELECT COUNT(*) FROM wearable_data"
        ).fetchone()[0]
    return {
        "total":               total,
        "urgente":             by_bucket.get("urgente",   0),
        "7_dias":              by_bucket.get("7_dias",    0),
        "2_semanas":           by_bucket.get("2_semanas", 0),
        "avg_score":           avg_score or 0.0,
        "n_patients":          n_patients,
        "total_wearable_days": total_wearable_days,
    }


def delete_triage(triage_id: int) -> bool:
    with _connect() as conn:
        cur = conn.execute("DELETE FROM triages WHERE id = ?", (triage_id,))
    return cur.rowcount > 0


def delete_all() -> int:
    with _connect() as conn:
        cur = conn.execute("DELETE FROM triages")
    return cur.rowcount


def delete_patient_data(patient_id: int) -> Dict[str, int]:
    """Elimina todos los datos de un paciente (triajes + wearable)."""
    with _connect() as conn:
        t = conn.execute("DELETE FROM triages      WHERE patient_id = ?", (patient_id,)).rowcount
        w = conn.execute("DELETE FROM wearable_data WHERE patient_id = ?", (patient_id,)).rowcount
        conn.execute("DELETE FROM patients WHERE id = ?", (patient_id,))
    return {"triages": t, "wearable_days": w}


def db_path() -> str:
    return str(_DB_PATH)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_decrypt(value: str) -> str:
    try:
        return decrypt(value)
    except Exception:
        return value


# ---------------------------------------------------------------------------
# Analisis clinicos
# ---------------------------------------------------------------------------

def save_lab_result(
    patient_id: int,
    raw_json: str,
    fecha: Optional[str] = None,
    laboratorio: Optional[str] = None,
    score_lab: int = 0,
    notes: str = "",
) -> int:
    """Guarda un analisis clinico para un paciente."""
    now = datetime.now().isoformat(timespec="seconds")
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO lab_results
               (patient_id, fecha, laboratorio, raw_json, score_lab, imported_at, notes)
               VALUES (?,?,?,?,?,?,?)""",
            (patient_id, fecha, laboratorio, raw_json, score_lab, now, notes),
        )
    return cur.lastrowid


def get_lab_results(patient_id: int) -> List[Dict[str, Any]]:
    """Devuelve todos los analisis de un paciente."""
    import json as _json
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM lab_results WHERE patient_id = ? ORDER BY imported_at DESC",
            (patient_id,),
        ).fetchall()
    results = []
    for r in rows:
        d = dict(r)
        try:
            d["data"] = _json.loads(d["raw_json"])
        except Exception:
            d["data"] = {}
        results.append(d)
    return results


def get_latest_lab(patient_id: int) -> Optional[Dict[str, Any]]:
    """Devuelve el analisis mas reciente de un paciente."""
    results = get_lab_results(patient_id)
    return results[0] if results else None
