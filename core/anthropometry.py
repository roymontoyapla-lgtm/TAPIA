# -*- coding: utf-8 -*-
"""
Calculo de indice de masa corporal (IMC) y riesgo por circunferencia
abdominal, segun los criterios de la OMS.

Referencias:
  - IMC: OMS (Organizacion Mundial de la Salud)
  - Circunferencia abdominal: umbrales de riesgo cardiovascular OMS/IDF
    Hombres: >94 cm riesgo aumentado, >102 cm riesgo muy aumentado
    Mujeres: >80 cm riesgo aumentado, >88 cm riesgo muy aumentado
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass
class AnthropometricData:
    """Datos antropometricos opcionales del paciente."""
    weight_kg: Optional[float] = None
    height_cm: Optional[float] = None
    waist_cm:  Optional[float] = None

    @property
    def has_data(self) -> bool:
        return any(v is not None for v in (self.weight_kg, self.height_cm, self.waist_cm))


# ---------------------------------------------------------------------------
# IMC
# ---------------------------------------------------------------------------

def compute_bmi(weight_kg: Optional[float], height_cm: Optional[float]) -> Optional[float]:
    """Calcula el IMC = peso(kg) / altura(m)^2. Devuelve None si faltan datos."""
    if not weight_kg or not height_cm or height_cm <= 0:
        return None
    height_m = height_cm / 100
    return round(weight_kg / (height_m ** 2), 1)


def bmi_category(bmi: Optional[float]) -> str:
    """Clasifica el IMC segun los criterios de la OMS."""
    if bmi is None:
        return "N/D"
    if bmi < 18.5:
        return "Bajo peso"
    if bmi < 25.0:
        return "Normopeso"
    if bmi < 30.0:
        return "Sobrepeso"
    if bmi < 35.0:
        return "Obesidad grado I"
    if bmi < 40.0:
        return "Obesidad grado II"
    return "Obesidad grado III (morbida)"


# ---------------------------------------------------------------------------
# Circunferencia abdominal
# ---------------------------------------------------------------------------

def waist_risk_category(waist_cm: Optional[float], sex: str) -> str:
    """
    Clasifica el riesgo cardiovascular por circunferencia abdominal
    segun sexo biologico (criterios OMS/IDF).
    """
    if waist_cm is None:
        return "N/D"

    sex_norm = (sex or "").upper()
    if sex_norm == "M":
        if waist_cm > 102:
            return "Riesgo muy aumentado"
        if waist_cm > 94:
            return "Riesgo aumentado"
        return "Riesgo normal"
    elif sex_norm == "F":
        if waist_cm > 88:
            return "Riesgo muy aumentado"
        if waist_cm > 80:
            return "Riesgo aumentado"
        return "Riesgo normal"
    else:
        # Sexo no especificado: usar umbral mas conservador (mujer)
        if waist_cm > 88:
            return "Riesgo muy aumentado"
        if waist_cm > 80:
            return "Riesgo aumentado"
        return "Riesgo normal"


# ---------------------------------------------------------------------------
# Score de urgencia por obesidad
# ---------------------------------------------------------------------------

def obesity_urgency_score(
    weight_kg: Optional[float],
    height_cm: Optional[float],
    waist_cm: Optional[float],
    sex: str,
) -> Tuple[int, List[str], Optional[float], str, str]:
    """
    Calcula puntos de urgencia por riesgo de obesidad.
    Devuelve (score, motivos, bmi, bmi_cat, waist_cat).
    """
    score = 0
    motivos: List[str] = []

    bmi     = compute_bmi(weight_kg, height_cm)
    bmi_cat = bmi_category(bmi)
    waist_cat = waist_risk_category(waist_cm, sex)

    if bmi is not None:
        if bmi >= 40:
            score += 4
            motivos.append(f"IMC {bmi} - Obesidad grado III / morbida (+4)")
        elif bmi >= 35:
            score += 3
            motivos.append(f"IMC {bmi} - Obesidad grado II (+3)")
        elif bmi >= 30:
            score += 2
            motivos.append(f"IMC {bmi} - Obesidad grado I (+2)")
        elif bmi >= 25:
            score += 1
            motivos.append(f"IMC {bmi} - Sobrepeso (+1)")
        elif bmi < 18.5:
            score += 2
            motivos.append(f"IMC {bmi} - Bajo peso (+2)")

    if waist_cm is not None:
        if waist_cat == "Riesgo muy aumentado":
            score += 2
            motivos.append(f"Circunferencia abdominal {waist_cm} cm - riesgo cardiovascular muy aumentado (+2)")
        elif waist_cat == "Riesgo aumentado":
            score += 1
            motivos.append(f"Circunferencia abdominal {waist_cm} cm - riesgo cardiovascular aumentado (+1)")

    return score, motivos, bmi, bmi_cat, waist_cat
