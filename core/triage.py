"""Lógica de triaje: AP vs especialista y score de urgencia."""

import logging
from typing import List, Tuple

from .config import cfg
from .models import PatientInfo, Questionnaire, WearableSummary

logger = logging.getLogger(__name__)

URGENCY_LABELS = {
    "urgente":   "URGENTE",
    "7_dias":    "Dentro de los próximos 7 días",
    "2_semanas": "En un periodo de 2 semanas",
}

URGENCY_ORDER = {"urgente": 2, "7_dias": 1, "2_semanas": 0}


# ---------------------------------------------------------------------------
# AP vs especialista
# ---------------------------------------------------------------------------

def triage_ap_vs_specialist(
    q: Questionnaire,
    w30: WearableSummary,
    w56: WearableSummary,
) -> Tuple[str, str, List[str]]:
    """
    Devuelve (recomendación, especialidad_sugerida, lista_de_motivos).
    """
    thr     = cfg.thresholds
    reasons: List[str] = []
    score_ap   = 0
    score_spec = 0
    spec = "-"

    if q.fever:
        score_ap += 2
        reasons.append("Refiere fiebre.")
    if q.headache_last_month:
        score_ap += 1
        reasons.append("Refiere dolor de cabeza en el último mes.")
    if q.general_feeling <= 2:
        score_ap += 2
        reasons.append("Estado general percibido bajo (1-2/5).")
    if q.rested_enough <= 2:
        score_ap += 1
        reasons.append("Refiere descanso insuficiente (1-2/5).")
    if q.exercise_days_last_weeks <= 1:
        score_ap += 1
        reasons.append("Actividad física muy baja reportada.")

    if w30.days > 0 and w30.low_sleep_days >= thr.sleep.low_days_month_ap:
        score_ap += 2
        reasons.append(
            f"Último mes: muchos días con sueño < {thr.sleep.low_hours}h "
            f"({w30.low_sleep_days}/{w30.days})."
        )
    if w56.days > 0 and w56.low_sleep_days >= thr.sleep.low_days_8w_ap:
        score_ap += 1
        reasons.append(
            f"Últimas 8 semanas: sueño < {thr.sleep.low_hours}h frecuente "
            f"({w56.low_sleep_days}/{w56.days})."
        )

    if w30.high_resting_hr_days >= thr.hr.high_days_specialist:
        score_spec += 3
        spec = "Cardiología (orientativo)"
        reasons.append(
            f"Último mes: varios días con pulso en reposo ≥ {thr.hr.high_resting_bpm} bpm "
            f"({w30.high_resting_hr_days} días)."
        )

    if w30.very_low_activity_days >= thr.activity.low_days_month_ap:
        score_ap += 1
        reasons.append(
            f"Último mes: muchos días con < {thr.activity.very_low_steps} pasos "
            f"({w30.very_low_activity_days}/{w30.days})."
        )

    rec = "Posible especialista" if score_spec >= 3 else "Médico de cabecera"
    reasons.insert(0, f"Puntuación orientativa → AP: {score_ap}, Especialista: {score_spec}.")

    if q.diet_style:
        reasons.append(f"Estilo de alimentación declarado: {q.diet_style}.")
    if q.other_notes:
        reasons.append(f"Enfermedad crónica/preexistente: {q.other_notes}.")

    return rec, spec, reasons


# ---------------------------------------------------------------------------
# Score de urgencia
# ---------------------------------------------------------------------------

def urgency_score_and_bucket(
    patient: PatientInfo,
    q: Questionnaire,
    w30: WearableSummary,
    w56: WearableSummary,
) -> Tuple[str, int, List[str]]:
    """
    Devuelve (bucket, score, lista_de_motivos).
    bucket ∈ {'urgente', '7_dias', '2_semanas'}
    """
    thr  = cfg.thresholds
    sc   = cfg.scoring
    urg  = cfg.urgency

    score  = 0
    motivos: List[str] = []

    # Edad
    if patient.age >= 75:
        score += sc.age_over_75;  motivos.append(f"Edad ≥75 (+{sc.age_over_75})")
    elif patient.age >= 65:
        score += sc.age_over_65;  motivos.append(f"Edad 65–74 (+{sc.age_over_65})")
    elif patient.age >= 50:
        score += sc.age_over_50;  motivos.append(f"Edad 50–64 (+{sc.age_over_50})")

    # Síntomas
    if q.fever:
        score += sc.fever;   motivos.append(f"Fiebre (+{sc.fever})")
    if q.headache_last_month:
        score += sc.headache; motivos.append(f"Cefalea último mes (+{sc.headache})")

    # Estado general
    if q.general_feeling <= 2:
        score += sc.general_bad;  motivos.append(f"Estado general bajo ≤2/5 (+{sc.general_bad})")
    elif q.general_feeling == 3:
        score += sc.general_fair; motivos.append(f"Estado general regular 3/5 (+{sc.general_fair})")

    # Descanso
    if q.rested_enough <= 2:
        score += sc.rest_bad;  motivos.append(f"Descanso insuficiente ≤2/5 (+{sc.rest_bad})")
    elif q.rested_enough == 3:
        score += sc.rest_fair; motivos.append(f"Descanso regular 3/5 (+{sc.rest_fair})")

    # Ejercicio
    if q.exercise_days_last_weeks <= 1:
        score += sc.exercise_very_low
        motivos.append(f"Muy poco ejercicio ≤1 día (+{sc.exercise_very_low})")
    elif q.exercise_days_last_weeks <= 3:
        score += sc.exercise_low
        motivos.append(f"Ejercicio bajo 2–3 días (+{sc.exercise_low})")

    # Wearable 30 días
    if w30.days > 0:
        if w30.low_sleep_days >= thr.sleep.low_days_month_urgent:
            score += 3
            motivos.append(
                f"Último mes: sueño <{thr.sleep.low_hours}h muy frecuente "
                f"({w30.low_sleep_days}/{w30.days}) (+3)"
            )
        elif w30.low_sleep_days >= thr.sleep.low_days_month_moderate:
            score += 2
            motivos.append(
                f"Último mes: sueño <{thr.sleep.low_hours}h frecuente "
                f"({w30.low_sleep_days}/{w30.days}) (+2)"
            )

        if w30.very_low_activity_days >= thr.activity.low_days_month_urgent:
            score += 2
            motivos.append(
                f"Último mes: actividad muy baja frecuente "
                f"({w30.very_low_activity_days}/{w30.days}) (+2)"
            )
        elif w30.very_low_activity_days >= thr.activity.low_days_month_moderate:
            score += 1
            motivos.append(
                f"Último mes: varios días con actividad muy baja "
                f"({w30.very_low_activity_days}/{w30.days}) (+1)"
            )

        if w30.high_resting_hr_days >= thr.hr.high_days_score_4:
            score += 4
            motivos.append(
                f"Último mes: FC reposo ≥{thr.hr.high_resting_bpm} bpm muy repetida "
                f"({w30.high_resting_hr_days} días) (+4)"
            )
        elif w30.high_resting_hr_days >= thr.hr.high_days_score_3:
            score += 3
            motivos.append(
                f"Último mes: FC reposo ≥{thr.hr.high_resting_bpm} bpm repetida "
                f"({w30.high_resting_hr_days} días) (+3)"
            )

    # Wearable 56 días
    if w56.days > 0 and w56.low_sleep_days >= thr.sleep.low_days_8w_persistent:
        score += 1
        motivos.append(
            f"Últimas 8 semanas: sueño <{thr.sleep.low_hours}h persistente "
            f"({w56.low_sleep_days}/{w56.days}) (+1)"
        )

    # Bonus combinado
    if q.fever and q.general_feeling <= 2:
        score += sc.fever_plus_bad_general
        motivos.append(f"Fiebre + mal estado general (+{sc.fever_plus_bad_general})")

    # Clasificación
    if score >= urg.urgent_threshold:
        bucket = "urgente"
    elif score >= urg.week_threshold:
        bucket = "7_dias"
    else:
        bucket = "2_semanas"

    motivos.insert(0, f"Score total: {score}")
    logger.debug("Urgency score=%d → %s", score, bucket)
    return bucket, score, motivos


def merge_buckets(local: str, ai: str) -> str:
    """Devuelve el bucket más urgente de los dos (estrategia conservadora)."""
    return local if URGENCY_ORDER.get(local, 0) >= URGENCY_ORDER.get(ai, 0) else ai
