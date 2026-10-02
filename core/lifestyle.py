# -*- coding: utf-8 -*-
"""
Motor de recomendaciones de alimentacion y ejercicio.

A partir de los datos que TAPIA ya recoge (antropometria, cuestionario,
wearable y analisis clinicos) genera un plan personalizado y DETERMINISTA:
no llama a ninguna IA, de modo que el resultado es reproducible y auditable.

Guias de referencia usadas:
  - OMS 2020: Directrices sobre actividad fisica y habitos sedentarios
    (150-300 min/semana de actividad aerobica moderada + 2 dias de fuerza;
     mayores de 65 anos anaden 3 dias de equilibrio).
  - OMS: sal < 5 g/dia, azucares libres < 10% de la energia diaria.
  - Mifflin-St Jeor para el gasto energetico basal.
  - EFSA/OMS: 25-30 g/dia de fibra, 1.2-1.5 g/kg de proteina en mayores.

IMPORTANTE: el plan es orientativo y de apoyo a la consulta. Cuando se
detectan senales de alarma el motor exige valoracion medica previa y
limita la prescripcion a actividad ligera.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from .anthropometry import bmi_category, compute_bmi, waist_risk_category
from .config import cfg

# Equivalencia energetica aproximada de 1 kg de tejido graso
KCAL_PER_KG = 7700.0

# Suelos de seguridad para la ingesta calorica (kcal/dia)
MIN_KCAL_MALE   = cfg.lifestyle.min_kcal_male
MIN_KCAL_FEMALE = cfg.lifestyle.min_kcal_female

# Objetivo aerobico semanal (OMS)
WHO_AEROBIC_MIN      = cfg.lifestyle.aerobic_min_week
WHO_AEROBIC_WEIGHT   = cfg.lifestyle.aerobic_min_week_weight   # perdida de peso sostenida
WHO_STRENGTH_DAYS    = cfg.lifestyle.strength_days
WHO_BALANCE_DAYS_65  = cfg.lifestyle.balance_days_65

DAYS_ES = ["Lunes", "Martes", "Miercoles", "Jueves", "Viernes", "Sabado", "Domingo"]


# ---------------------------------------------------------------------------
# Estructuras de salida
# ---------------------------------------------------------------------------

@dataclass
class EnergyPlan:
    """Balance energetico estimado."""
    bmr:              Optional[int] = None
    tdee:             Optional[int] = None
    target_kcal:      Optional[int] = None
    objective:        str = "mantener"           # perder_peso | mantener | ganar_peso
    objective_label:  str = "Mantener el peso"
    daily_delta_kcal: int = 0
    weekly_change_kg: Optional[float] = None
    activity_factor:  float = 1.2
    activity_label:   str = "Sedentario"
    healthy_weight_range: Optional[Tuple[float, float]] = None


@dataclass
class NutritionPlan:
    """Recomendaciones de alimentacion."""
    energy:       EnergyPlan = field(default_factory=EnergyPlan)
    pattern:      str = "Dieta mediterranea"
    protein_g:    Optional[int] = None
    carbs_g:      Optional[int] = None
    fat_g:        Optional[int] = None
    fiber_g:      int = 25
    water_ml:     int = 2000
    salt_g_max:   float = 5.0
    protein_note: str = ""
    priorities:   List[str] = field(default_factory=list)
    prefer:       List[str] = field(default_factory=list)
    limit:        List[str] = field(default_factory=list)
    habits:       List[str] = field(default_factory=list)
    sample_day:   List[Tuple[str, str]] = field(default_factory=list)


@dataclass
class ExercisePlan:
    """Prescripcion de ejercicio progresiva."""
    baseline_steps:        Optional[int] = None
    baseline_weekly_min:   int = 0
    weekly_min_start:      int = 0
    weekly_min_target:     int = WHO_AEROBIC_MIN
    sessions_per_week:     int = 3
    minutes_per_session:   int = 20
    strength_sessions:     int = WHO_STRENGTH_DAYS
    balance_sessions:      int = 0
    steps_goal:            int = 7000
    intensity:             str = "Moderada"
    weekly_schedule:       List[Tuple[str, str]] = field(default_factory=list)
    progression:           List[str] = field(default_factory=list)
    restrictions:          List[str] = field(default_factory=list)


@dataclass
class LifestylePlan:
    """Plan completo de alimentacion y ejercicio."""
    generated_at:      str = ""
    patient_name:      str = ""
    patient_age:       Optional[int] = None
    patient_sex:       str = ""
    bmi:               Optional[float] = None
    bmi_category:      str = "N/D"
    waist_category:    str = "N/D"
    nutrition:         NutritionPlan = field(default_factory=NutritionPlan)
    exercise:          ExercisePlan  = field(default_factory=ExercisePlan)
    medical_clearance: bool = False
    cautions:          List[str] = field(default_factory=list)
    goals:             List[str] = field(default_factory=list)
    data_used:         List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Normalizacion de entradas
# ---------------------------------------------------------------------------

def _get(obj: Any, key: str, default: Any = None) -> Any:
    """Lee un campo tanto de un dict como de un dataclass/objeto."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        val = obj.get(key, default)
    else:
        val = getattr(obj, key, default)
    return default if val is None else val


def _num(value: Any) -> Optional[float]:
    """Convierte a float lo que se pueda; None en caso contrario."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _norm_sex(sex: Any) -> str:
    s = str(sex or "").strip().upper()
    if s.startswith("M") or s in ("H", "HOMBRE", "VARON"):
        return "M"
    if s.startswith("F") or s == "MUJER":
        return "F"
    return "X"


# ---------------------------------------------------------------------------
# Gasto energetico
# ---------------------------------------------------------------------------

def basal_metabolic_rate(
    weight_kg: Optional[float],
    height_cm: Optional[float],
    age: Optional[int],
    sex: str,
) -> Optional[int]:
    """
    Gasto energetico basal por la ecuacion de Mifflin-St Jeor.
    Para sexo no especificado se promedian las dos constantes.
    """
    w, h = _num(weight_kg), _num(height_cm)
    a = _num(age)
    if not w or not h or not a or w <= 0 or h <= 0 or a <= 0:
        return None

    base = 10 * w + 6.25 * h - 5 * a
    sex_n = _norm_sex(sex)
    if sex_n == "M":
        base += 5
    elif sex_n == "F":
        base -= 161
    else:
        base += (5 - 161) / 2
    return int(round(base))


def activity_factor(
    avg_steps: Optional[float],
    avg_exercise_min: Optional[float],
    exercise_days_week: Optional[int] = None,
) -> Tuple[float, str]:
    """
    Estima el factor de actividad a partir del wearable. Si no hay wearable
    usa los dias de ejercicio declarados en el cuestionario.
    """
    steps = _num(avg_steps)
    ex    = _num(avg_exercise_min)

    if steps is None and ex is None:
        days = _num(exercise_days_week) or 0
        if days >= 5:
            return 1.55, "Moderadamente activo (declarado)"
        if days >= 3:
            return 1.375, "Ligeramente activo (declarado)"
        return 1.2, "Sedentario (declarado)"

    steps = steps or 0.0
    ex    = ex or 0.0

    if steps >= 10000 or ex >= 60:
        return 1.725, "Muy activo"
    if steps >= 7500 or ex >= 40:
        return 1.55, "Moderadamente activo"
    if steps >= 5000 or ex >= 20:
        return 1.375, "Ligeramente activo"
    return 1.2, "Sedentario"


def healthy_weight_range(height_cm: Optional[float]) -> Optional[Tuple[float, float]]:
    """Rango de peso correspondiente a un IMC de 18.5 a 24.9."""
    h = _num(height_cm)
    if not h or h <= 0:
        return None
    m = h / 100
    return (round(18.5 * m * m, 1), round(24.9 * m * m, 1))


def build_energy_plan(
    weight_kg: Optional[float],
    height_cm: Optional[float],
    age: Optional[int],
    sex: str,
    bmi: Optional[float],
    avg_steps: Optional[float] = None,
    avg_exercise_min: Optional[float] = None,
    exercise_days_week: Optional[int] = None,
) -> EnergyPlan:
    """Calcula BMR, gasto total y objetivo calorico segun el IMC."""
    factor, label = activity_factor(avg_steps, avg_exercise_min, exercise_days_week)
    plan = EnergyPlan(
        activity_factor=factor,
        activity_label=label,
        healthy_weight_range=healthy_weight_range(height_cm),
    )

    bmr = basal_metabolic_rate(weight_kg, height_cm, age, sex)
    if bmr is None:
        # Sin peso/altura no se puede estimar la energia: plan cualitativo
        if bmi is not None and bmi >= 25:
            plan.objective, plan.objective_label = "perder_peso", "Reducir peso corporal"
        return plan

    tdee = int(round(bmr * factor))
    plan.bmr, plan.tdee, plan.target_kcal = bmr, tdee, tdee

    if bmi is None:
        return plan

    if bmi >= 30:
        deficit = int(min(600, round(tdee * 0.25)))
        plan.objective, plan.objective_label = "perder_peso", "Reducir peso corporal"
    elif bmi >= 25:
        deficit = int(min(500, round(tdee * 0.20)))
        plan.objective, plan.objective_label = "perder_peso", "Reducir peso corporal"
    elif bmi < 18.5:
        deficit = -400
        plan.objective, plan.objective_label = "ganar_peso", "Recuperar peso corporal"
    else:
        return plan

    target = tdee - deficit
    floor  = MIN_KCAL_MALE if _norm_sex(sex) == "M" else MIN_KCAL_FEMALE
    if deficit > 0 and target < floor:
        target  = floor
        deficit = tdee - floor

    plan.target_kcal      = int(round(target))
    plan.daily_delta_kcal = int(round(-deficit))
    plan.weekly_change_kg = round(-deficit * 7 / KCAL_PER_KG, 2)
    return plan


# ---------------------------------------------------------------------------
# Lectura de los analisis clinicos
# ---------------------------------------------------------------------------

def _lab_flags(lab_data: Optional[Dict[str, Any]], sex: str) -> Dict[str, Any]:
    """
    Traduce los valores del analisis en banderas dieteticas.
    Devuelve {flags:set, priorities:list, prefer:list, limit:list, alerts:list}.
    """
    out: Dict[str, Any] = {
        "flags": set(), "priorities": [], "prefer": [], "limit": [], "alerts": [],
    }
    if not lab_data:
        return out

    bio = lab_data.get("bioquimica") or {}
    hem = lab_data.get("hemograma")  or {}
    sex_n = _norm_sex(sex)

    glucosa = _num(bio.get("glucosa_mg_dl"))
    hba1c   = _num(bio.get("hba1c_pct"))
    if (glucosa is not None and glucosa >= 126) or (hba1c is not None and hba1c >= 6.5):
        out["flags"].add("diabetes")
        out["priorities"].append(
            "Glucemia en rango diabetico: repartir los hidratos en todas las comidas, "
            "priorizar los de bajo indice glucemico y acompanarlos siempre de fibra o proteina."
        )
        out["limit"] += ["Azucar, bolleria y zumos (incluidos los naturales)",
                         "Harinas refinadas y arroz blanco"]
        out["alerts"].append("Glucemia compatible con diabetes: requiere confirmacion y seguimiento medico.")
    elif (glucosa is not None and glucosa >= 100) or (hba1c is not None and hba1c >= 5.7):
        out["flags"].add("prediabetes")
        out["priorities"].append(
            "Glucemia en rango de prediabetes: reducir azucares libres y cereales refinados; "
            "una perdida del 5-7% del peso revierte gran parte del riesgo."
        )
        out["limit"].append("Refrescos azucarados, bolleria y postres industriales")

    ldl   = _num(bio.get("colesterol_ldl_mg_dl"))
    total = _num(bio.get("colesterol_total_mg_dl"))
    if (ldl is not None and ldl >= 130) or (total is not None and total >= 240):
        out["flags"].add("colesterol")
        out["priorities"].append(
            "Colesterol elevado: sustituir grasas saturadas por aceite de oliva virgen extra "
            "y anadir fibra soluble (avena, legumbres, manzana)."
        )
        out["prefer"] += ["Avena y cebada", "Frutos secos sin sal (un punado al dia)",
                          "Pescado azul 2-3 veces por semana"]
        out["limit"]  += ["Embutidos, mantequilla y nata", "Bolleria y fritos industriales"]

    tg = _num(bio.get("trigliceridos_mg_dl"))
    if tg is not None and tg >= 150:
        out["flags"].add("trigliceridos")
        out["priorities"].append(
            "Trigliceridos elevados: suprimir alcohol y azucares simples; el omega-3 "
            "del pescado azul ayuda a bajarlos."
        )
        out["limit"] += ["Alcohol", "Fructosa anadida y refrescos"]

    hdl = _num(bio.get("colesterol_hdl_mg_dl"))
    if hdl is not None and ((sex_n == "M" and hdl < 40) or (sex_n != "M" and hdl < 50)):
        out["flags"].add("hdl_bajo")
        out["priorities"].append(
            "HDL bajo: el ejercicio aerobico regular y las grasas monoinsaturadas "
            "(aceite de oliva, aguacate, frutos secos) son la medida mas eficaz."
        )

    urico = _num(bio.get("acido_urico_mg_dl"))
    if urico is not None and urico >= 7.0:
        out["flags"].add("urico")
        out["priorities"].append(
            "Acido urico elevado: limitar visceras, mariscos, carnes rojas, cerveza "
            "y refrescos con fructosa; asegurar 2-2.5 L de agua al dia."
        )
        out["limit"] += ["Visceras, marisco y carnes rojas", "Cerveza y licores"]

    creat = _num(bio.get("creatinina_mg_dl"))
    if creat is not None and ((sex_n == "M" and creat > 1.3) or (sex_n != "M" and creat > 1.1)):
        out["flags"].add("renal")
        out["priorities"].append(
            "Creatinina elevada: NO aumentar la proteina ni usar suplementos proteicos "
            "hasta valorar la funcion renal; vigilar la sal."
        )
        out["alerts"].append("Creatinina elevada: la pauta proteica debe confirmarla el medico.")

    alt = _num(bio.get("alt_u_l"))
    ast = _num(bio.get("ast_u_l"))
    ggt = _num(bio.get("ggt_u_l"))
    if (alt is not None and alt > 40) or (ast is not None and ast > 40) or (ggt is not None and ggt > 60):
        out["flags"].add("higado")
        out["priorities"].append(
            "Enzimas hepaticas elevadas: alcohol cero y perdida gradual de peso "
            "(7-10%), que es el tratamiento de eleccion del higado graso."
        )
        out["limit"].append("Alcohol (cero)")

    hb  = _num(hem.get("hemoglobina_g_dl"))
    fer = _num(bio.get("ferritina_ng_ml"))
    if (hb is not None and ((sex_n == "M" and hb < 13) or (sex_n != "M" and hb < 12))) or \
       (fer is not None and fer < 30):
        out["flags"].add("anemia")
        out["priorities"].append(
            "Hierro bajo o anemia: combinar alimentos ricos en hierro (legumbres, carne magra, "
            "verdura de hoja verde) con vitamina C, y separarlos del cafe y el te."
        )
        out["prefer"].append("Legumbres y verdura de hoja verde con citricos")
    if hb is not None and hb < 10:
        out["alerts"].append("Anemia significativa (Hb < 10 g/dL): evitar ejercicio intenso hasta valoracion medica.")

    vitd = _num(bio.get("vitamina_d_ng_ml"))
    if vitd is not None and vitd < 20:
        out["flags"].add("vitamina_d")
        out["priorities"].append(
            "Vitamina D baja: 15-20 min diarios de exposicion solar prudente y pescado azul, "
            "huevo y lacteos enriquecidos. Valorar suplementacion con el medico."
        )

    tsh = _num(bio.get("tsh_uui_ml"))
    if tsh is not None and tsh > 4.5:
        out["alerts"].append("TSH elevada: revisar funcion tiroidea antes de atribuir el peso a la dieta.")

    pcr = _num(bio.get("pcr_mg_l"))
    if pcr is not None and pcr > 10:
        out["alerts"].append("PCR elevada: posible proceso inflamatorio activo; posponer el inicio de entrenamientos intensos.")

    k = _num(bio.get("potasio_meq_l"))
    if k is not None and (k < 3.5 or k > 5.5):
        out["alerts"].append("Potasio fuera de rango: no modificar la dieta rica en potasio sin control medico.")

    if glucosa is not None and glucosa >= 200:
        out["alerts"].append("Glucemia >= 200 mg/dL: valoracion medica antes de iniciar ejercicio.")

    return out


# ---------------------------------------------------------------------------
# Patron alimentario
# ---------------------------------------------------------------------------

_PATTERNS = {
    "vegana": {
        "keys": ("vegan",),
        "label": "Vegana (base mediterranea)",
        "protein": ["Legumbres, tofu, tempeh y seitan", "Frutos secos y semillas"],
        "note": "Vigilar vitamina B12 (suplemento obligado), hierro, zinc y omega-3.",
    },
    "vegetariana": {
        "keys": ("vegetarian", "ovolacte"),
        "label": "Vegetariana (base mediterranea)",
        "protein": ["Legumbres, huevo y lacteos", "Tofu, frutos secos y semillas"],
        "note": "Combinar legumbre y cereal para completar la proteina; vigilar hierro y B12.",
    },
    "sin_gluten": {
        "keys": ("gluten", "celiac"),
        "label": "Sin gluten (base mediterranea)",
        "protein": ["Legumbres, pescado, huevo y carne magra"],
        "note": "Sustituir el cereal por arroz, quinoa, trigo sarraceno o maiz certificados.",
    },
    "mediterranea": {
        "keys": ("mediterran",),
        "label": "Dieta mediterranea",
        "protein": ["Pescado, legumbres, huevo y carne magra"],
        "note": "",
    },
}


def _detect_pattern(diet_style: str) -> Dict[str, Any]:
    text = (diet_style or "").strip().lower()
    for cfg_key, data in _PATTERNS.items():
        if any(k in text for k in data["keys"]):
            return data
    base = dict(_PATTERNS["mediterranea"])
    if text:
        base["label"] = f"Dieta mediterranea (declarado: {diet_style.strip()})"
    return base


# Sustituciones para que ninguna recomendacion contradiga el patron elegido
_PLANT_SWAPS = {
    "vegana": {
        "swaps": [
            ("legumbres, carne magra, verdura de hoja verde",
             "legumbres, tofu, semillas de calabaza y verdura de hoja verde"),
            ("pescado azul, huevo y lacteos enriquecidos",
             "bebidas vegetales y cereales enriquecidos"),
            ("Pescado azul 2-3 veces por semana",
             "Nueces y semillas de lino o chia (omega-3 vegetal)"),
        ],
        "drop": ["visceras", "marisco", "embutidos, mantequilla y nata", "carne procesada"],
    },
    "vegetariana": {
        "swaps": [
            ("legumbres, carne magra, verdura de hoja verde",
             "legumbres, huevo y verdura de hoja verde"),
            ("pescado azul, huevo y lacteos enriquecidos",
             "huevo y lacteos enriquecidos"),
            ("Pescado azul 2-3 veces por semana",
             "Nueces y semillas de lino o chia (omega-3 vegetal)"),
        ],
        "drop": ["visceras", "marisco", "carne procesada"],
    },
}


def _adapt_to_pattern(pattern_label: str, items: List[str]) -> List[str]:
    """Reescribe o elimina las recomendaciones incompatibles con el patron."""
    key = "vegana" if "Vegana" in pattern_label else (
          "vegetariana" if "Vegetariana" in pattern_label else None)
    if key is None:
        return items

    rules = _PLANT_SWAPS[key]
    out: List[str] = []
    for item in items:
        text = item
        for old_txt, new_txt in rules["swaps"]:
            text = text.replace(old_txt, new_txt)
        if any(d in text.lower() for d in rules["drop"]):
            continue
        out.append(text)
    return out


def _sample_day(pattern: Dict[str, Any], flags: set) -> List[Tuple[str, str]]:
    """Ejemplo de dia adaptado al patron y a las banderas clinicas."""
    low_gi = "diabetes" in flags or "prediabetes" in flags
    cereal = "pan integral" if not low_gi else "pan integral 100% (racion medida)"

    if "Vegana" in pattern["label"]:
        protein_lunch = "legumbre (garbanzos, lentejas) o tofu"
        protein_dinner = "tempeh o hummus"
        breakfast_protein = "bebida vegetal enriquecida y frutos secos"
    elif "Vegetariana" in pattern["label"]:
        protein_lunch = "legumbre o huevo"
        protein_dinner = "tortilla o queso fresco"
        breakfast_protein = "yogur natural o kefir"
    else:
        protein_lunch = "pescado, legumbre o carne magra"
        protein_dinner = "pescado blanco, huevo o legumbre"
        breakfast_protein = "yogur natural, huevo o queso fresco"

    return [
        ("Desayuno", f"Fruta entera + {breakfast_protein} + {cereal} con aceite de oliva virgen extra"),
        ("Media manana", "Fruta o un punado de frutos secos sin sal"),
        ("Comida", f"Medio plato de verdura + {protein_lunch} + racion de cereal integral o patata + fruta"),
        ("Merienda", "Yogur natural, fruta o verdura cruda"),
        ("Cena", f"Verdura cocinada o ensalada + {protein_dinner} + fruta"),
        ("Bebida", "Agua como bebida principal; sin refrescos ni alcohol"),
    ]


def build_nutrition_plan(
    energy: EnergyPlan,
    weight_kg: Optional[float],
    height_cm: Optional[float],
    age: Optional[int],
    bmi: Optional[float],
    diet_style: str = "",
    lab: Optional[Dict[str, Any]] = None,
) -> NutritionPlan:
    """Construye las recomendaciones nutricionales (macros + pautas)."""
    lab = lab or {"flags": set(), "priorities": [], "prefer": [], "limit": [], "alerts": []}
    flags = lab["flags"]
    pattern = _detect_pattern(diet_style)

    plan = NutritionPlan(energy=energy, pattern=pattern["label"])
    age_v = _num(age) or 0
    w     = _num(weight_kg)

    # --- Proteina: referencia sobre peso saludable si hay sobrepeso ---
    ref_weight = w
    if w and height_cm and bmi is not None and bmi >= 25:
        m = _num(height_cm) / 100
        ref_weight = round(25 * m * m, 1)

    if "renal" in flags:
        g_kg, note = 0.8, "Proteina limitada a 0.8 g/kg por creatinina elevada; confirmar con el medico."
    elif age_v >= 65:
        g_kg, note = 1.3, "Proteina alta (1.3 g/kg) para prevenir perdida de masa muscular."
    elif energy.objective == "perder_peso":
        g_kg, note = 1.4, "Proteina alta (1.4 g/kg) para conservar masa muscular durante la perdida de peso."
    elif energy.objective == "ganar_peso":
        g_kg, note = 1.5, "Proteina alta (1.5 g/kg) junto con trabajo de fuerza para ganar masa magra."
    else:
        g_kg, note = 1.2, "Proteina de mantenimiento (1.2 g/kg)."

    if ref_weight:
        plan.protein_g = int(round(ref_weight * g_kg))
        plan.protein_note = note + f" Referencia: {ref_weight} kg x {g_kg} g/kg."

    # --- Reparto de macros sobre el objetivo calorico ---
    if energy.target_kcal:
        kcal = energy.target_kcal
        fat_kcal = kcal * 0.30
        plan.fat_g = int(round(fat_kcal / 9))
        prot_kcal = (plan.protein_g or 0) * 4
        carbs_kcal = max(kcal - fat_kcal - prot_kcal, kcal * 0.30)
        plan.carbs_g = int(round(carbs_kcal / 4))
        plan.fiber_g = max(25, int(round(14 * kcal / 1000)))

    # --- Hidratacion: 30-35 ml/kg sobre el peso de referencia, con tope de 3 L ---
    if ref_weight:
        ml_kg = 30 if age_v >= 65 else 35
        target_ml = int(round(ref_weight * ml_kg / 100.0) * 100)
        plan.water_ml = max(1500, min(3000, target_ml))
    if "urico" in flags:
        plan.water_ml = max(plan.water_ml, 2500)

    # --- Prioridades ---
    priorities: List[str] = []
    if energy.objective == "perder_peso" and energy.weekly_change_kg:
        priorities.append(
            f"Deficit de {abs(energy.daily_delta_kcal)} kcal/dia sobre un gasto estimado de "
            f"{energy.tdee} kcal: perdida prevista de {abs(energy.weekly_change_kg)} kg/semana "
            f"(objetivo realista: 5-10% del peso en 6 meses)."
        )
    elif energy.objective == "ganar_peso":
        priorities.append(
            f"Superavit de {energy.daily_delta_kcal} kcal/dia con alimentos densos en nutrientes "
            "(frutos secos, aceite de oliva, legumbres, lacteos enteros)."
        )
    else:
        priorities.append("Mantener el peso actual con un patron mediterraneo y comidas regulares.")

    priorities += _adapt_to_pattern(plan.pattern, lab["priorities"])
    if pattern["note"]:
        priorities.append(pattern["note"])
    plan.priorities = priorities

    # --- Listas de alimentos ---
    plan.prefer = _adapt_to_pattern(plan.pattern, _dedup([
        "Verdura y hortalizas en comida y cena (medio plato)",
        "Fruta entera 2-3 piezas al dia",
        "Legumbres 3-4 veces por semana",
        "Cereales integrales en lugar de refinados",
        "Aceite de oliva virgen extra como grasa principal",
    ] + pattern["protein"] + lab["prefer"]))

    plan.limit = _adapt_to_pattern(plan.pattern, _dedup([
        "Ultraprocesados, bolleria y precocinados",
        "Bebidas azucaradas y zumos",
        "Carne procesada (embutidos, salchichas)",
        f"Sal: maximo {plan.salt_g_max:.0f} g/dia (usar especias y hierbas)",
        "Alcohol",
    ] + lab["limit"]))

    plan.habits = [
        "Comer sin pantallas y despacio; parar al notar saciedad.",
        "Planificar la compra con lista y no comprar con hambre.",
        "Cocinado al horno, plancha, vapor o guiso; evitar fritos.",
        f"Beber unos {plan.water_ml} ml de agua al dia, mas si hace calor o hay ejercicio.",
        "Cenar al menos 2 horas antes de acostarse para mejorar el descanso.",
    ]
    plan.sample_day = _sample_day(pattern, flags)
    return plan


def _dedup(items: List[str]) -> List[str]:
    """Elimina duplicados conservando el orden."""
    seen, out = set(), []
    for it in items:
        key = it.strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(it)
    return out


# ---------------------------------------------------------------------------
# Seguridad: cuando hace falta valoracion medica antes de entrenar
# ---------------------------------------------------------------------------

# Antecedentes que obligan a autorizacion medica previa (ACSM/OMS)
CLEARANCE_KEYWORDS = (
    "cardio", "corazon", "infarto", "angina", "arritmia", "marcapasos",
    "insuficiencia cardiaca", "valvul", "ictus", "acv", "epoc", "enfisema",
    "asma grave", "embaraz", "cancer", "oncolog", "dialisis", "anticoagul",
)

# Antecedentes que no impiden entrenar pero exigen bajo impacto
LOW_IMPACT_KEYWORDS = (
    "artrosis", "artritis", "rodilla", "cadera", "lumbar", "espalda",
    "hernia", "protesis", "fibromialgia", "varices", "fascitis",
)


def _matches(text: str, keywords: Tuple[str, ...]) -> List[str]:
    t = (text or "").lower()
    return [k for k in keywords if k in t]


def safety_review(
    age: Optional[int],
    bmi: Optional[float],
    fever: bool,
    final_bucket: str,
    avg_resting_hr: Optional[float],
    high_resting_hr_days: int,
    chronic_notes: str,
    lab_alerts: List[str],
) -> Tuple[bool, List[str], List[str]]:
    """
    Decide si se necesita autorizacion medica antes de iniciar ejercicio.
    Devuelve (clearance_requerida, avisos, restricciones).
    """
    cautions: List[str] = []
    restrictions: List[str] = []
    clearance = False

    if final_bucket == "urgente":
        clearance = True
        cautions.append(
            "El triaje ha clasificado el caso como URGENTE: resolver primero el motivo "
            "de consulta antes de iniciar cualquier programa de ejercicio."
        )
    if fever:
        clearance = True
        cautions.append("Fiebre actual: no entrenar hasta 48-72 h despues de quedar afebril.")

    hr = _num(avg_resting_hr)
    if (hr is not None and hr >= 90) or (high_resting_hr_days or 0) >= 5:
        clearance = True
        cautions.append(
            "Frecuencia cardiaca en reposo elevada de forma mantenida: valorar causa "
            "antes de progresar a intensidades moderadas o altas."
        )

    if bmi is not None and bmi >= 40:
        clearance = True
        cautions.append("IMC >= 40: iniciar con supervision y priorizar actividad sin impacto.")
        restrictions.append("Actividad sin impacto: agua, bicicleta estatica o eliptica.")
    elif bmi is not None and bmi >= 35:
        restrictions.append("Preferir bajo impacto (agua, bicicleta, eliptica) para proteger rodillas y caderas.")

    age_v = _num(age) or 0
    if age_v >= 75:
        cautions.append("Mayor de 75 anos: incluir trabajo de equilibrio y progresar mas despacio.")

    found = _matches(chronic_notes, CLEARANCE_KEYWORDS)
    if found:
        clearance = True
        cautions.append(
            "Antecedentes declarados que requieren autorizacion medica previa: "
            + ", ".join(found) + "."
        )

    low_impact = _matches(chronic_notes, LOW_IMPACT_KEYWORDS)
    if low_impact:
        restrictions.append(
            "Problemas osteoarticulares declarados (" + ", ".join(low_impact) +
            "): evitar carrera y saltos; usar agua, bicicleta o caminar."
        )

    if "diabet" in (chronic_notes or "").lower():
        restrictions.append(
            "Diabetes: medir glucemia antes y despues, llevar hidratos de absorcion rapida "
            "y revisar los pies tras cada sesion."
        )
    if "hipertens" in (chronic_notes or "").lower():
        restrictions.append(
            "Hipertension: evitar maniobras de Valsalva y cargas maximas; priorizar aerobico continuo."
        )

    for alert in lab_alerts:
        cautions.append(alert)
        low = alert.lower()
        if "anemia" in low or "glucemia >= 200" in low or "inflamatorio" in low:
            clearance = True

    return clearance, _dedup(cautions), _dedup(restrictions)


# ---------------------------------------------------------------------------
# Prescripcion de ejercicio
# ---------------------------------------------------------------------------

def _round_to(value: float, step: int) -> int:
    return int(round(value / step) * step)


def _round_up(value: float, step: int) -> int:
    return int(-(-value // step) * step)


def build_exercise_plan(
    age: Optional[int],
    bmi: Optional[float],
    objective: str,
    avg_steps: Optional[float] = None,
    avg_exercise_min: Optional[float] = None,
    exercise_days_week: Optional[int] = None,
    clearance: bool = False,
    restrictions: Optional[List[str]] = None,
) -> ExercisePlan:
    """
    Prescripcion progresiva basada en las directrices de la OMS 2020,
    partiendo del nivel real de actividad del paciente.
    """
    plan = ExercisePlan(restrictions=list(restrictions or []))
    age_v = _num(age) or 0

    steps = _num(avg_steps)
    plan.baseline_steps = int(round(steps)) if steps is not None else None

    ex_min = _num(avg_exercise_min)
    if ex_min is not None:
        baseline = int(round(ex_min * 7))
    else:
        baseline = int((_num(exercise_days_week) or 0) * 30)
    plan.baseline_weekly_min = baseline

    # Objetivo semanal
    target = WHO_AEROBIC_MIN
    if objective == "perder_peso" or (bmi is not None and bmi >= 25):
        target = WHO_AEROBIC_WEIGHT
    plan.weekly_min_target = target

    # Punto de partida: progresion sobre lo que ya hace, nunca de cero a todo
    if baseline >= target:
        start = target
    else:
        start = max(45, _round_to(baseline * 1.2, 5))
        start = min(start, target)
    plan.weekly_min_start = start

    plan.sessions_per_week = 3 if start <= 90 else (4 if start <= 180 else 5)
    plan.minutes_per_session = max(10, _round_to(start / plan.sessions_per_week, 5))

    plan.strength_sessions = WHO_STRENGTH_DAYS
    plan.balance_sessions  = WHO_BALANCE_DAYS_65 if age_v >= 65 else 0

    # Objetivo de pasos
    if plan.baseline_steps is not None:
        plan.steps_goal = int(min(10000, max(5000, _round_up(plan.baseline_steps + 2000, 500))))
    else:
        plan.steps_goal = 7000

    if clearance:
        plan.intensity = "Ligera hasta contar con autorizacion medica"
    elif baseline >= WHO_AEROBIC_MIN:
        plan.intensity = "Moderada a vigorosa (puede hablar con frases cortas)"
    else:
        plan.intensity = "Moderada (puede hablar, no cantar)"

    plan.weekly_schedule = _weekly_schedule(plan, age_v)
    plan.progression = _progression_notes(plan, clearance)
    return plan


def _weekly_schedule(plan: ExercisePlan, age_v: float) -> List[Tuple[str, str]]:
    """Reparte las sesiones en la semana de forma alterna."""
    aerobic_days = {
        3: [0, 2, 4],
        4: [0, 2, 4, 6],
        5: [0, 1, 3, 4, 6],
    }.get(plan.sessions_per_week, [0, 2, 4])
    strength_days = [1, 4] if plan.strength_sessions >= 2 else [1]

    schedule: List[Tuple[str, str]] = []
    for i, day in enumerate(DAYS_ES):
        tasks: List[str] = []
        if i in aerobic_days:
            tasks.append(f"Aerobico {plan.minutes_per_session} min ({plan.intensity.split('(')[0].strip().lower()})")
        if i in strength_days:
            tasks.append("Fuerza 20-30 min (piernas, empuje, traccion, core)")
        if plan.balance_sessions and i in (1, 3, 5):
            tasks.append("Equilibrio 10 min (apoyo unipodal, talon-punta)")
        if not tasks:
            tasks.append("Descanso activo: paseo suave y movilidad 10 min")
        schedule.append((day, " + ".join(tasks)))
    return schedule


def _progression_notes(plan: ExercisePlan, clearance: bool) -> List[str]:
    notes = [
        f"Semana 1-2: {plan.weekly_min_start} min/semana repartidos en "
        f"{plan.sessions_per_week} sesiones de {plan.minutes_per_session} min.",
        "Aumentar un 10% el tiempo semanal cada semana mientras no aparezcan molestias.",
    ]
    if plan.weekly_min_target > plan.weekly_min_start:
        weeks = 0
        current = float(plan.weekly_min_start)
        while current < plan.weekly_min_target and weeks < 52:
            current *= 1.10
            weeks += 1
        notes.append(
            f"Objetivo: {plan.weekly_min_target} min/semana (alcanzable en unas {weeks} semanas "
            "a ese ritmo de progresion)."
        )
    else:
        notes.append(f"Mantener los {plan.weekly_min_target} min/semana ya alcanzados y variar los estimulos.")

    notes.append(f"Pasos: objetivo diario de {plan.steps_goal} pasos, subiendo 500-1000 pasos por semana.")
    notes.append(f"Fuerza: {plan.strength_sessions} dias por semana, 2-3 series de 8-12 repeticiones por grupo muscular.")
    if plan.balance_sessions:
        notes.append(f"Equilibrio: {plan.balance_sessions} dias por semana para prevenir caidas.")
    notes.append("Reducir el tiempo sentado: levantarse 3-5 min cada hora.")
    if clearance:
        notes.insert(0, "PENDIENTE DE AUTORIZACION MEDICA: hasta entonces, solo paseo suave y movilidad.")
    notes.append(
        "Parar y consultar si aparece dolor toracico, mareo, palpitaciones o disnea desproporcionada."
    )
    return notes


# ---------------------------------------------------------------------------
# Objetivos de seguimiento
# ---------------------------------------------------------------------------

def build_goals(
    energy: EnergyPlan,
    exercise: ExercisePlan,
    weight_kg: Optional[float],
    waist_cm: Optional[float],
    sex: str,
    bmi: Optional[float],
    low_sleep_days: int = 0,
    lab_flags: Optional[set] = None,
) -> List[str]:
    """Objetivos medibles a 8-12 semanas."""
    goals: List[str] = []
    flags = lab_flags or set()
    w = _num(weight_kg)

    if energy.objective == "perder_peso" and w:
        goals.append(
            f"Perder {round(w * 0.05, 1)}-{round(w * 0.10, 1)} kg (5-10% del peso) en 6 meses."
        )
        if energy.healthy_weight_range:
            lo, hi = energy.healthy_weight_range
            goals.append(f"Peso saludable de referencia para su altura: {lo}-{hi} kg.")
    elif energy.objective == "ganar_peso" and energy.healthy_weight_range:
        lo, hi = energy.healthy_weight_range
        goals.append(f"Alcanzar progresivamente {lo}-{hi} kg con trabajo de fuerza.")
    elif bmi is not None:
        goals.append(f"Mantener el IMC en {bmi} y la composicion corporal actual.")

    waist = _num(waist_cm)
    if waist is not None:
        limit = 94 if _norm_sex(sex) == "M" else 80
        if waist > limit:
            goals.append(
                f"Reducir la circunferencia abdominal de {waist} cm a menos de {limit} cm "
                "(la medida que mas se asocia al riesgo cardiovascular)."
            )
        else:
            goals.append(f"Mantener la circunferencia abdominal por debajo de {limit} cm.")

    goals.append(f"Alcanzar {exercise.weekly_min_target} min/semana de actividad aerobica.")
    goals.append(f"Llegar a {exercise.steps_goal} pasos diarios de media.")
    goals.append(f"Realizar {exercise.strength_sessions} sesiones de fuerza cada semana.")

    if low_sleep_days >= 8:
        goals.append("Dormir 7-8 h: reducir a menos de 4 las noches de menos de 6 h al mes.")
    if "diabetes" in flags or "prediabetes" in flags:
        goals.append("Repetir glucemia y HbA1c en 3 meses.")
    if "colesterol" in flags or "trigliceridos" in flags:
        goals.append("Repetir el perfil lipidico en 3 meses.")

    goals.append("Revision del plan a las 4 semanas para ajustar cargas y raciones.")
    return _dedup(goals)


# ---------------------------------------------------------------------------
# Punto de entrada
# ---------------------------------------------------------------------------

def build_lifestyle_plan(
    patient: Any,
    q: Any = None,
    anthro: Optional[Dict[str, Any]] = None,
    w30: Any = None,
    lab_data: Optional[Dict[str, Any]] = None,
    final_bucket: str = "2_semanas",
) -> LifestylePlan:
    """
    Construye el plan de alimentacion y ejercicio del paciente.

    `patient` admite PatientInfo o dict (name, age, sex).
    `q`       admite Questionnaire o dict (diet_style, exercise_days_last_weeks,
              fever, rested_enough, other_notes).
    `anthro`  dict con weight_kg, height_cm, waist_cm (y opcionalmente bmi).
    `w30`     WearableSummary o dict con las medias de los ultimos 30 dias.
    `lab_data` dict con la estructura que devuelve core.lab_analyzer.
    """
    anthro = anthro or {}

    name = str(_get(patient, "name", "") or "")
    age  = _num(_get(patient, "age"))
    sex  = str(_get(patient, "sex", "") or "")

    weight = _num(anthro.get("weight_kg"))
    height = _num(anthro.get("height_cm"))
    waist  = _num(anthro.get("waist_cm"))
    bmi    = _num(anthro.get("bmi")) or compute_bmi(weight, height)

    diet_style = str(_get(q, "diet_style", "") or "")
    chronic    = str(_get(q, "other_notes", "") or "")
    fever      = bool(_get(q, "fever", False))
    ex_days    = _num(_get(q, "exercise_days_last_weeks"))
    rested     = _num(_get(q, "rested_enough"))

    avg_steps     = _num(_get(w30, "avg_steps"))
    avg_ex_min    = _num(_get(w30, "avg_exercise_min"))
    avg_hr        = _num(_get(w30, "avg_resting_hr"))
    low_sleep     = int(_num(_get(w30, "low_sleep_days", 0)) or 0)
    high_hr_days  = int(_num(_get(w30, "high_resting_hr_days", 0)) or 0)
    avg_sleep     = _num(_get(w30, "avg_sleep_h"))

    lab = _lab_flags(lab_data, sex)

    energy = build_energy_plan(
        weight_kg=weight, height_cm=height, age=age, sex=sex, bmi=bmi,
        avg_steps=avg_steps, avg_exercise_min=avg_ex_min,
        exercise_days_week=int(ex_days) if ex_days is not None else None,
    )
    nutrition = build_nutrition_plan(
        energy=energy, weight_kg=weight, height_cm=height, age=age, bmi=bmi,
        diet_style=diet_style, lab=lab,
    )

    clearance, cautions, restrictions = safety_review(
        age=age, bmi=bmi, fever=fever, final_bucket=final_bucket,
        avg_resting_hr=avg_hr, high_resting_hr_days=high_hr_days,
        chronic_notes=chronic, lab_alerts=lab["alerts"],
    )
    exercise = build_exercise_plan(
        age=age, bmi=bmi, objective=energy.objective,
        avg_steps=avg_steps, avg_exercise_min=avg_ex_min,
        exercise_days_week=int(ex_days) if ex_days is not None else None,
        clearance=clearance, restrictions=restrictions,
    )

    # Sueno y descanso influyen en el apetito y la adherencia
    if low_sleep >= 8 or (rested is not None and rested <= 2) or (avg_sleep is not None and avg_sleep < 6):
        nutrition.habits.append(
            "Descanso insuficiente: dormir menos de 6 h aumenta el apetito y dificulta "
            "la perdida de peso. Horario regular, sin pantallas la ultima hora y sin cafeina despues de las 16 h."
        )

    data_used: List[str] = []
    if anthro.get("weight_kg") or anthro.get("height_cm") or anthro.get("waist_cm"):
        data_used.append("Antropometria (peso, altura, circunferencia abdominal)")
    if avg_steps is not None or avg_ex_min is not None:
        data_used.append(f"Wearable ({int(_num(_get(w30, 'days', 0)) or 0)} dias)")
    if lab_data:
        data_used.append("Analisis clinico")
    if diet_style or chronic or ex_days is not None:
        data_used.append("Cuestionario clinico")
    if not data_used:
        data_used.append("Sin datos objetivos: plan generico")

    return LifestylePlan(
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        patient_name=name,
        patient_age=int(age) if age else None,
        patient_sex=sex,
        bmi=bmi,
        bmi_category=bmi_category(bmi),
        waist_category=waist_risk_category(waist, sex),
        nutrition=nutrition,
        exercise=exercise,
        medical_clearance=clearance,
        cautions=cautions,
        goals=build_goals(
            energy, exercise, weight, waist, sex, bmi,
            low_sleep_days=low_sleep, lab_flags=lab["flags"],
        ),
        data_used=data_used,
    )


# ---------------------------------------------------------------------------
# Render en texto plano (para descarga, PDF y contexto de la IA)
# ---------------------------------------------------------------------------

def _fmt(value: Any, unit: str = "") -> str:
    return f"{value}{unit}" if value is not None else "N/D"


def render_plan_text(plan: LifestylePlan) -> str:
    """Convierte el plan en un informe de texto legible."""
    n, e = plan.nutrition, plan.exercise
    en = n.energy

    lines = [
        "=" * 60,
        "  PLAN DE ALIMENTACION Y EJERCICIO  -  TAPIA",
        "=" * 60,
        f"  Generado: {plan.generated_at}",
        "",
        "-- 0) PACIENTE " + "-" * 44,
        f"  Nombre : {plan.patient_name or 'N/D'}",
        f"  Edad   : {_fmt(plan.patient_age, ' anos')}",
        f"  Sexo   : {plan.patient_sex or 'N/D'}",
        f"  IMC    : {_fmt(plan.bmi)}  ({plan.bmi_category})",
        f"  Riesgo por circunferencia abdominal: {plan.waist_category}",
        f"  Datos utilizados: {', '.join(plan.data_used)}",
    ]

    if plan.medical_clearance:
        lines += [
            "",
            "  *** REQUIERE AUTORIZACION MEDICA ANTES DE INICIAR EL EJERCICIO ***",
        ]

    if plan.cautions:
        lines += ["", "-- 1) AVISOS DE SEGURIDAD " + "-" * 33]
        lines += [f"    ! {c}" for c in plan.cautions]

    lines += [
        "",
        "-- 2) BALANCE ENERGETICO " + "-" * 35,
        f"  Objetivo             : {en.objective_label}",
        f"  Nivel de actividad   : {en.activity_label} (factor {en.activity_factor})",
        f"  Gasto basal estimado : {_fmt(en.bmr, ' kcal/dia')}",
        f"  Gasto total estimado : {_fmt(en.tdee, ' kcal/dia')}",
        f"  Ingesta objetivo     : {_fmt(en.target_kcal, ' kcal/dia')}",
    ]
    if en.weekly_change_kg:
        lines.append(f"  Cambio previsto      : {en.weekly_change_kg} kg/semana")
    if en.healthy_weight_range:
        lo, hi = en.healthy_weight_range
        lines.append(f"  Peso saludable       : {lo}-{hi} kg (IMC 18.5-24.9)")

    lines += [
        "",
        "-- 3) ALIMENTACION " + "-" * 41,
        f"  Patron        : {n.pattern}",
        f"  Proteina      : {_fmt(n.protein_g, ' g/dia')}",
        f"  Hidratos      : {_fmt(n.carbs_g, ' g/dia')}",
        f"  Grasas        : {_fmt(n.fat_g, ' g/dia')}",
        f"  Fibra         : {n.fiber_g} g/dia",
        f"  Agua          : {n.water_ml} ml/dia",
        f"  Sal           : maximo {n.salt_g_max:.0f} g/dia",
    ]
    if n.protein_note:
        lines.append(f"  Nota proteina : {n.protein_note}")

    lines += ["", "  Prioridades:"]
    lines += [f"    - {p}" for p in n.priorities]
    lines += ["", "  Alimentos a priorizar:"]
    lines += [f"    + {p}" for p in n.prefer]
    lines += ["", "  Alimentos a limitar:"]
    lines += [f"    - {p}" for p in n.limit]
    lines += ["", "  Habitos:"]
    lines += [f"    . {h}" for h in n.habits]
    lines += ["", "  Ejemplo de dia:"]
    lines += [f"    {meal:<14}: {content}" for meal, content in n.sample_day]

    lines += [
        "",
        "-- 4) EJERCICIO " + "-" * 44,
        f"  Punto de partida : {e.baseline_weekly_min} min/semana"
        + (f" | {e.baseline_steps} pasos/dia" if e.baseline_steps is not None else ""),
        f"  Intensidad       : {e.intensity}",
        f"  Inicio           : {e.weekly_min_start} min/semana "
        f"({e.sessions_per_week} sesiones x {e.minutes_per_session} min)",
        f"  Objetivo OMS     : {e.weekly_min_target} min/semana",
        f"  Fuerza           : {e.strength_sessions} dias/semana",
    ]
    if e.balance_sessions:
        lines.append(f"  Equilibrio       : {e.balance_sessions} dias/semana")
    lines.append(f"  Pasos objetivo   : {e.steps_goal}/dia")

    lines += ["", "  Semana tipo:"]
    lines += [f"    {day:<10}: {task}" for day, task in e.weekly_schedule]
    lines += ["", "  Progresion:"]
    lines += [f"    - {p}" for p in e.progression]
    if e.restrictions:
        lines += ["", "  Adaptaciones:"]
        lines += [f"    - {r}" for r in e.restrictions]

    lines += ["", "-- 5) OBJETIVOS DE SEGUIMIENTO " + "-" * 29]
    lines += [f"    - {g}" for g in plan.goals]

    lines += [
        "",
        "-" * 60,
        "  Plan orientativo basado en las directrices de la OMS.",
        "  No sustituye la valoracion medica ni la consulta con dietista-nutricionista.",
        "-" * 60,
    ]
    return "\n".join(lines)
