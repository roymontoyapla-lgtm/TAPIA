"""Construcción del informe de texto."""

from datetime import datetime
from typing import Any, Dict, List

from .models import PatientInfo, Questionnaire, WearableSummary
from .triage import URGENCY_LABELS


def _fmt(val, unit: str = "") -> str:
    return f"{val}{unit}" if val is not None else "N/D"


def build_report(
    patient: PatientInfo,
    q: Questionnaire,
    w30: WearableSummary,
    w56: WearableSummary,
    rec: str,
    spec: str,
    reasons: List[str],
    local_bucket: str,
    local_score: int,
    local_motivos: List[str],
    ai: Dict[str, Any],
    final_bucket: str,
) -> str:
    now       = datetime.now().strftime("%Y-%m-%d %H:%M")
    ai_bucket = ai.get("urgency", "2_semanas")

    lines = [
        "=" * 60,
        "  INFORME ORIENTATIVO DE TRIAJE  –  TAPIA v1.1",
        "=" * 60,
        f"  Generado: {now}",
        "",
        "── 0) PACIENTE " + "─" * 44,
        f"  Nombre : {patient.name}",
        f"  Edad   : {patient.age}",
        f"  Sexo   : {patient.sex}",
        "",
        "── 1) CUESTIONARIO " + "─" * 40,
        f"  Dolor de cabeza último mes  : {'Sí' if q.headache_last_month else 'No'}",
        f"  Fiebre                      : {'Sí' if q.fever else 'No'}",
        f"  Estado general   (1–5)      : {q.general_feeling}",
        f"  Descanso suficiente (1–5)   : {q.rested_enough}",
        f"  Días ejercicio (ult. sem.)  : {q.exercise_days_last_weeks}",
        f"  Alimentación                : {q.diet_style or 'N/D'}",
        f"  Enfermedad crónica          : {q.other_notes or 'N/D'}",
        "",
        "── 2) WEARABLE – ÚLTIMO MES " + "─" * 31,
        f"  Días: {w30.days}  |  Rango: {w30.range}",
        f"  FC reposo media       : {_fmt(w30.avg_resting_hr, ' bpm')}",
        f"  Pasos medios/día      : {_fmt(w30.avg_steps)}",
        f"  Ejercicio medio       : {_fmt(w30.avg_exercise_min, ' min/día')}",
        f"  Sueño medio           : {_fmt(w30.avg_sleep_h, ' h/día')}",
        f"  Días sueño < 6h       : {w30.low_sleep_days}",
        f"  Días < 3 000 pasos    : {w30.very_low_activity_days}",
        f"  Días FC reposo ≥ 90   : {w30.high_resting_hr_days}",
        "",
        "── 3) WEARABLE – ÚLTIMAS 8 SEMANAS " + "─" * 23,
        f"  Días: {w56.days}  |  Rango: {w56.range}",
        f"  Sueño medio  : {_fmt(w56.avg_sleep_h, ' h/día')}  |  Días < 6h: {w56.low_sleep_days}",
        "",
        "── 4) AP VS. ESPECIALISTA " + "─" * 33,
        f"  Resultado                  : {rec}",
        f"  Especialidad sugerida      : {spec}",
        "  Motivos:",
        *[f"    · {r}" for r in reasons[:6]],
        "",
        "── 5) PRIORIZACIÓN DE CITA " + "─" * 32,
        f"  Prioridad local  : {URGENCY_LABELS[local_bucket]}  (score: {local_score})",
        *[f"    · {m}" for m in local_motivos[:6]],
        "",
        f"  Prioridad IA     : {URGENCY_LABELS.get(ai_bucket, URGENCY_LABELS['2_semanas'])}",
    ]

    if ai.get("_model_used"):
        lines.append(f"    (Modelo: {ai['_model_used']})")
    if ai.get("justification"):
        lines.append(f"    Justificación: {ai['justification']}")
    if ai.get("red_flags"):
        lines.append("    Banderas rojas:")
        lines += [f"      ⚑ {rf}" for rf in ai["red_flags"]]

    lines += [
        "",
        f"  ★ PRIORIDAD FINAL (conservadora): {URGENCY_LABELS[final_bucket]}",
        "",
        "─" * 60,
        "  ⚠  Informe orientativo. No sustituye valoración clínica.",
        "─" * 60,
    ]

    return "\n".join(lines)
