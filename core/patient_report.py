# -*- coding: utf-8 -*-
"""
Generador de informe clinico integral del paciente mediante Claude.

Sintetiza toda la informacion disponible:
  - Historial de triajes
  - Datos del wearable (tendencias)
  - Analisis clinicos
  - Cuestionarios previos

Y genera un informe narrativo cualitativo que ayuda al medico
a tener una vision global del estado de salud del paciente.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from statistics import mean
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Eres un asistente clinico de apoyo a la decision medica.
Se te proporcionara un resumen completo de los datos de salud de un paciente.
Tu tarea es generar un INFORME CLINICO INTEGRAL, narrativo y cualitativo.

El informe debe:
1. Dar una vision general del estado de salud del paciente
2. Identificar patrones preocupantes o positivos en sus datos
3. Destacar las areas de mayor atencion clinica
4. Relacionar los diferentes datos entre si (por ejemplo: mal sueno + glucosa alta + sedentarismo)
5. Sugerir areas de seguimiento o exploracion adicional
6. Usar un lenguaje clinico pero comprensible

El informe NO debe:
- Dar diagnosticos definitivos
- Prescribir medicacion
- Sustituir la valoracion clinica del medico

Estructura el informe con estas secciones claramente separadas:
## RESUMEN EJECUTIVO
## ESTADO CARDIOVASCULAR Y ACTIVIDAD FISICA
## PATRON DE SUENO Y RECUPERACION
## PARAMETROS ANALITICOS
## ESTADO GENERAL Y SINTOMATOLOGIA
## TENDENCIAS Y EVOLUCION
## AREAS DE ATENCION PRIORITARIA
## RECOMENDACIONES DE SEGUIMIENTO

Se conciso pero completo. Usa datos concretos cuando los tengas.
Responde en español."""


def _format_wearable_summary(records: List[Dict]) -> str:
    """Resume las metricas del wearable en texto para el prompt."""
    if not records:
        return "No hay datos de wearable disponibles."

    def avg(key):
        vals = [r.get(key) for r in records if r.get(key) is not None]
        return round(mean(vals), 1) if vals else None

    def pct_below(key, threshold):
        vals = [r.get(key) for r in records if r.get(key) is not None]
        if not vals:
            return None
        return round(sum(1 for v in vals if v < threshold) / len(vals) * 100, 1)

    n = len(records)
    fechas = sorted([r.get("fecha","") for r in records if r.get("fecha")])
    rango  = f"{fechas[0]} a {fechas[-1]}" if fechas else "N/D"

    hr_avg   = avg("pulso_reposo_bpm_media")
    steps_avg= avg("pasos")
    sleep_avg= avg("sueno_asleep_horas")
    ex_avg   = avg("min_ejercicio")
    hrv_avg  = avg("hrv_sdnn_ms_media")

    low_sleep_pct  = pct_below("sueno_asleep_horas", 6)
    low_steps_pct  = pct_below("pasos", 3000)
    high_hr_pct    = pct_below("pulso_reposo_bpm_media", -90)  # invertido

    # contar dias con FC alta
    hr_high = sum(1 for r in records
                  if r.get("pulso_reposo_bpm_media") and r["pulso_reposo_bpm_media"] >= 90)

    lines = [
        f"Periodo analizado: {rango} ({n} dias)",
        f"FC reposo media: {hr_avg} bpm" if hr_avg else "",
        f"Dias con FC reposo >= 90 bpm: {hr_high}/{n}",
        f"Pasos medios/dia: {steps_avg}" if steps_avg else "",
        f"Dias con < 3000 pasos: {sum(1 for r in records if r.get('pasos') and r['pasos']<3000)}/{n}",
        f"Sueno medio: {sleep_avg} h/noche" if sleep_avg else "",
        f"Dias con sueno < 6h: {sum(1 for r in records if r.get('sueno_asleep_horas') and r['sueno_asleep_horas']<6)}/{n}",
        f"Ejercicio medio: {ex_avg} min/dia" if ex_avg else "",
        f"HRV medio (SDNN): {hrv_avg} ms" if hrv_avg else "",
    ]
    return "\n".join(l for l in lines if l)


def _format_lab_results(lab_list: List[Dict]) -> str:
    """Resume los analisis clinicos para el prompt."""
    if not lab_list:
        return "No hay analisis clinicos disponibles."

    lines = []
    for i, lab in enumerate(lab_list[:3]):  # maximo 3 analisis
        data  = lab.get("data", {})
        fecha = lab.get("fecha") or lab.get("imported_at", "")[:10]
        lines.append(f"\nAnalisis {i+1} (fecha: {fecha}):")

        hema = data.get("hemograma", {})
        bio  = data.get("bioquimica", {})
        orina= data.get("orina", {})

        for section, d in [("Hemograma", hema), ("Bioquimica", bio), ("Orina", orina)]:
            vals = {k: v for k, v in d.items() if v is not None}
            if vals:
                lines.append(f"  {section}:")
                for k, v in vals.items():
                    lines.append(f"    {k.replace('_',' ')}: {v}")

        fuera = data.get("valores_fuera_rango", [])
        if fuera:
            lines.append(f"  VALORES FUERA DE RANGO: {', '.join(str(f) for f in fuera)}")

    return "\n".join(lines)


def _format_triage_history(triages: List[Dict]) -> str:
    """Resume el historial de triajes para el prompt."""
    if not triages:
        return "No hay triajes previos."

    bucket_map = {
        "urgente":   "URGENTE",
        "7_dias":    "7 dias",
        "2_semanas": "2 semanas",
    }
    lines = []
    for t in triages[:5]:  # ultimos 5
        fecha  = t.get("created_at", "")[:10]
        bucket = bucket_map.get(t.get("final_bucket",""), t.get("final_bucket",""))
        score  = t.get("local_score", "?")
        lines.append(f"- {fecha}: prioridad {bucket} (score {score})")
    return "\n".join(lines)


def build_patient_context(
    patient: Dict[str, Any],
    wearable_records: List[Dict],
    lab_results: List[Dict],
    triage_history: List[Dict],
) -> str:
    """Construye el contexto completo del paciente para enviar a Claude."""
    age = patient.get("age", "?")
    sex = patient.get("sex", "?")
    sex_label = "Hombre" if sex == "M" else "Mujer" if sex == "F" else sex

    context = f"""DATOS DEL PACIENTE
==================
Edad: {age} años | Sexo: {sex_label}
Fecha del informe: {datetime.now().strftime("%d/%m/%Y")}

HISTORIAL DE WEARABLE ({len(wearable_records)} dias)
==================
{_format_wearable_summary(wearable_records)}

ANALISIS CLINICOS ({len(lab_results)} disponibles)
==================
{_format_lab_results(lab_results)}

HISTORIAL DE TRIAJES ({len(triage_history)} registros)
==================
{_format_triage_history(triage_history)}
"""
    return context


def generate_patient_report(
    patient: Dict[str, Any],
    wearable_records: List[Dict],
    lab_results: List[Dict],
    triage_history: List[Dict],
) -> str:
    """
    Genera el informe clinico integral del paciente usando Claude.
    Devuelve el texto del informe.
    """
    try:
        import anthropic
    except ImportError:
        return "Error: anthropic no instalado. Instala con: pip install anthropic"

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        return "Error: ANTHROPIC_API_KEY no configurada."

    context = build_patient_context(
        patient, wearable_records, lab_results, triage_history
    )

    # Anonimizar nombre antes de enviar
    patient_name = patient.get("name", "PACIENTE")

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=3000,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Genera el informe clinico integral para este paciente "
                        f"(identificado como PACIENTE, {patient.get('age')} años, "
                        f"sexo {patient.get('sex')}):\n\n{context}"
                    ),
                }
            ],
        )
        report_text = response.content[0].text
        logger.info("Informe integral generado para patient_id=%s", patient.get("id"))
        return report_text

    except Exception as e:
        logger.error("Error generando informe integral: %s", e)
        return f"Error al generar el informe: {e}"
