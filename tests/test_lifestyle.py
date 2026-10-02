# -*- coding: utf-8 -*-
"""
Tests del motor de recomendaciones de alimentacion y ejercicio.

El motor es deterministico: no llama a ninguna IA, asi que todo se
puede comprobar con valores exactos.
"""

from __future__ import annotations

import pytest

from tapia.core.lifestyle import (
    MIN_KCAL_FEMALE,
    MIN_KCAL_MALE,
    WHO_AEROBIC_MIN,
    WHO_AEROBIC_WEIGHT,
    activity_factor,
    basal_metabolic_rate,
    build_energy_plan,
    build_exercise_plan,
    build_lifestyle_plan,
    healthy_weight_range,
    render_plan_text,
    safety_review,
)
from tapia.core.models import PatientInfo, Questionnaire, WearableSummary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _wearable(steps=6000.0, ex_min=25.0, hr=65.0, sleep=7.2,
              low_sleep=2, high_hr=0, days=30):
    return WearableSummary(
        days=days, range="2026-01-01 a 2026-01-30",
        avg_resting_hr=hr, avg_steps=steps, avg_exercise_min=ex_min,
        avg_sleep_h=sleep, avg_resp=15.0, avg_hrv=45.0,
        low_sleep_days=low_sleep, very_low_activity_days=0,
        high_resting_hr_days=high_hr,
    )


def _questionnaire(diet="mediterranea", chronic="", fever=False, ex_days=3, rested=4):
    return Questionnaire(
        headache_last_month=False, fever=fever, general_feeling=3,
        diet_style=diet, rested_enough=rested,
        exercise_days_last_weeks=ex_days, other_notes=chronic,
    )


# ---------------------------------------------------------------------------
# Gasto energetico
# ---------------------------------------------------------------------------

class TestEnergy:

    def test_bmr_hombre_mifflin(self):
        # 10*80 + 6.25*180 - 5*40 + 5 = 1730
        assert basal_metabolic_rate(80, 180, 40, "M") == 1730

    def test_bmr_mujer_mifflin(self):
        # 10*65 + 6.25*165 - 5*35 - 161 = 1345.25 -> 1345
        assert basal_metabolic_rate(65, 165, 35, "F") == 1345

    def test_bmr_sexo_no_especificado_promedia(self):
        hombre = basal_metabolic_rate(70, 170, 30, "M")
        mujer  = basal_metabolic_rate(70, 170, 30, "F")
        otro   = basal_metabolic_rate(70, 170, 30, "Otro")
        assert mujer < otro < hombre

    @pytest.mark.parametrize("weight,height,age", [
        (None, 180, 40), (80, None, 40), (80, 180, None), (0, 180, 40),
    ])
    def test_bmr_sin_datos_devuelve_none(self, weight, height, age):
        assert basal_metabolic_rate(weight, height, age, "M") is None

    def test_factor_actividad_por_pasos(self):
        assert activity_factor(2000, 0)[0]  == 1.2
        assert activity_factor(6000, 10)[0] == 1.375
        assert activity_factor(8000, 10)[0] == 1.55
        assert activity_factor(12000, 10)[0] == 1.725

    def test_factor_actividad_sin_wearable_usa_cuestionario(self):
        factor, label = activity_factor(None, None, exercise_days_week=5)
        assert factor == 1.55
        assert "declarado" in label

    def test_deficit_en_obesidad(self):
        plan = build_energy_plan(100, 175, 45, "M", bmi=32.7, avg_steps=4000, avg_exercise_min=10)
        assert plan.objective == "perder_peso"
        assert plan.target_kcal < plan.tdee
        assert plan.weekly_change_kg is not None and plan.weekly_change_kg < 0

    def test_superavit_en_bajo_peso(self):
        plan = build_energy_plan(45, 170, 30, "F", bmi=15.6, avg_steps=6000, avg_exercise_min=20)
        assert plan.objective == "ganar_peso"
        assert plan.target_kcal > plan.tdee

    def test_normopeso_mantiene(self):
        plan = build_energy_plan(70, 175, 35, "M", bmi=22.9, avg_steps=8000, avg_exercise_min=30)
        assert plan.objective == "mantener"
        assert plan.target_kcal == plan.tdee

    def test_suelo_calorico_de_seguridad(self):
        # Mujer mayor y de baja estatura: el deficit no puede bajar del suelo
        plan = build_energy_plan(62, 150, 80, "F", bmi=27.6, avg_steps=1500, avg_exercise_min=0)
        assert plan.target_kcal >= MIN_KCAL_FEMALE

    def test_suelo_calorico_hombre(self):
        plan = build_energy_plan(75, 160, 78, "M", bmi=29.3, avg_steps=1000, avg_exercise_min=0)
        assert plan.target_kcal >= MIN_KCAL_MALE

    def test_rango_peso_saludable(self):
        lo, hi = healthy_weight_range(175)
        assert lo == pytest.approx(56.7, abs=0.1)
        assert hi == pytest.approx(76.3, abs=0.1)
        assert healthy_weight_range(None) is None


# ---------------------------------------------------------------------------
# Nutricion
# ---------------------------------------------------------------------------

class TestNutrition:

    def _plan(self, **kw):
        args = dict(
            patient=PatientInfo(name="Test", age=45, sex="M"),
            q=_questionnaire(),
            anthro={"weight_kg": 95.0, "height_cm": 178.0, "waist_cm": 106.0},
            w30=_wearable(steps=4000.0, ex_min=10.0),
            lab_data=None,
            final_bucket="2_semanas",
        )
        args.update(kw)
        return build_lifestyle_plan(**args)

    def test_macros_coherentes_con_las_calorias(self):
        plan = self._plan()
        n = plan.nutrition
        kcal = n.protein_g * 4 + n.carbs_g * 4 + n.fat_g * 9
        assert abs(kcal - n.energy.target_kcal) <= 60

    def test_proteina_alta_en_perdida_de_peso(self):
        plan = self._plan()
        assert "1.4 g/kg" in plan.nutrition.protein_note

    def test_proteina_limitada_si_creatinina_alta(self):
        plan = self._plan(lab_data={"bioquimica": {"creatinina_mg_dl": 1.6}})
        assert "0.8 g/kg" in plan.nutrition.protein_note
        assert any("creatinina" in p.lower() for p in plan.nutrition.priorities)

    def test_hidratacion_con_tope(self):
        plan = self._plan(anthro={"weight_kg": 150.0, "height_cm": 175.0, "waist_cm": 130.0})
        assert plan.nutrition.water_ml <= 3000

    def test_patron_vegano_detectado(self):
        plan = self._plan(q=_questionnaire(diet="dieta vegana estricta"))
        assert "Vegana" in plan.nutrition.pattern
        assert any("B12" in p for p in plan.nutrition.priorities)
        assert not any("pescado" in f.lower() for f in plan.nutrition.prefer)

    def test_recomendaciones_de_laboratorio_se_adaptan_al_patron_vegano(self):
        plan = self._plan(
            q=_questionnaire(diet="vegana"),
            lab_data={
                "hemograma":  {"hemoglobina_g_dl": 11.0},
                "bioquimica": {"vitamina_d_ng_ml": 12, "colesterol_ldl_mg_dl": 180},
            },
        )
        texto = " ".join(plan.nutrition.priorities + plan.nutrition.prefer + plan.nutrition.limit).lower()
        for animal in ["carne magra", "pescado azul", "visceras", "marisco", "carne procesada"]:
            assert animal not in texto
        assert any("hierro" in p.lower() for p in plan.nutrition.priorities)

    def test_recomendaciones_vegetarianas_conservan_huevo(self):
        plan = self._plan(
            q=_questionnaire(diet="vegetariana"),
            lab_data={"hemograma": {"hemoglobina_g_dl": 11.0}},
        )
        texto = " ".join(plan.nutrition.priorities).lower()
        assert "carne magra" not in texto
        assert "huevo" in texto

    def test_patron_sin_gluten_detectado(self):
        plan = self._plan(q=_questionnaire(diet="celiaca, sin gluten"))
        assert "Sin gluten" in plan.nutrition.pattern

    def test_diabetes_genera_prioridad_y_limites(self):
        plan = self._plan(lab_data={"bioquimica": {"glucosa_mg_dl": 140, "hba1c_pct": 7.1}})
        assert any("diabetic" in p.lower() for p in plan.nutrition.priorities)
        assert any("azucar" in f.lower() for f in plan.nutrition.limit)

    def test_prediabetes_detectada(self):
        plan = self._plan(lab_data={"bioquimica": {"glucosa_mg_dl": 108}})
        assert any("prediabetes" in p.lower() for p in plan.nutrition.priorities)

    def test_colesterol_y_trigliceridos(self):
        plan = self._plan(lab_data={"bioquimica": {
            "colesterol_ldl_mg_dl": 175, "trigliceridos_mg_dl": 260,
        }})
        texto = " ".join(plan.nutrition.priorities).lower()
        assert "colesterol" in texto and "trigliceridos" in texto

    def test_sin_datos_no_rompe(self):
        plan = build_lifestyle_plan(patient={"name": "X", "age": 50, "sex": "F"})
        assert plan.nutrition.energy.target_kcal is None
        assert plan.exercise.weekly_min_target == WHO_AEROBIC_MIN
        assert "Sin datos objetivos" in plan.data_used[0]


# ---------------------------------------------------------------------------
# Ejercicio
# ---------------------------------------------------------------------------

class TestExercise:

    def test_objetivo_300_min_si_sobrepeso(self):
        plan = build_exercise_plan(age=45, bmi=31.0, objective="perder_peso",
                                   avg_steps=4000, avg_exercise_min=10)
        assert plan.weekly_min_target == WHO_AEROBIC_WEIGHT

    def test_objetivo_150_min_si_normopeso(self):
        plan = build_exercise_plan(age=45, bmi=22.0, objective="mantener",
                                   avg_steps=8000, avg_exercise_min=25)
        assert plan.weekly_min_target == WHO_AEROBIC_MIN

    def test_inicio_progresivo_desde_el_nivel_actual(self):
        # 10 min/dia = 70 min/semana -> arranca por encima pero sin saltar al objetivo
        plan = build_exercise_plan(age=45, bmi=31.0, objective="perder_peso",
                                   avg_steps=4000, avg_exercise_min=10)
        assert 70 <= plan.weekly_min_start < plan.weekly_min_target

    def test_sedentario_total_arranca_en_45_min(self):
        plan = build_exercise_plan(age=50, bmi=28.0, objective="perder_peso",
                                   avg_steps=1500, avg_exercise_min=0)
        assert plan.weekly_min_start == 45
        assert plan.sessions_per_week == 3

    def test_paciente_ya_activo_mantiene_objetivo(self):
        plan = build_exercise_plan(age=35, bmi=23.0, objective="mantener",
                                   avg_steps=12000, avg_exercise_min=60)
        assert plan.weekly_min_start == plan.weekly_min_target
        assert "vigorosa" in plan.intensity.lower()

    def test_equilibrio_en_mayores_de_65(self):
        joven = build_exercise_plan(age=40, bmi=24.0, objective="mantener")
        mayor = build_exercise_plan(age=70, bmi=24.0, objective="mantener")
        assert joven.balance_sessions == 0
        assert mayor.balance_sessions == 3
        assert any("Equilibrio" in t for _, t in mayor.weekly_schedule)

    def test_objetivo_de_pasos_sobre_la_base(self):
        plan = build_exercise_plan(age=40, bmi=24.0, objective="mantener", avg_steps=4200)
        assert plan.steps_goal == 6500

    def test_objetivo_de_pasos_con_tope(self):
        plan = build_exercise_plan(age=40, bmi=24.0, objective="mantener", avg_steps=11000)
        assert plan.steps_goal == 10000

    def test_semana_completa(self):
        plan = build_exercise_plan(age=40, bmi=24.0, objective="mantener", avg_steps=6000)
        assert len(plan.weekly_schedule) == 7
        assert sum(1 for _, t in plan.weekly_schedule if "Fuerza" in t) == 2

    def test_intensidad_ligera_si_falta_autorizacion(self):
        plan = build_exercise_plan(age=60, bmi=41.0, objective="perder_peso", clearance=True)
        assert "autorizacion" in plan.intensity.lower()
        assert "AUTORIZACION" in plan.progression[0]


# ---------------------------------------------------------------------------
# Seguridad
# ---------------------------------------------------------------------------

class TestSafety:

    def _review(self, **kw):
        args = dict(
            age=45, bmi=26.0, fever=False, final_bucket="2_semanas",
            avg_resting_hr=65.0, high_resting_hr_days=0,
            chronic_notes="", lab_alerts=[],
        )
        args.update(kw)
        return safety_review(**args)

    def test_caso_normal_no_requiere_autorizacion(self):
        clearance, cautions, _ = self._review()
        assert clearance is False
        assert cautions == []

    def test_triaje_urgente_requiere_autorizacion(self):
        clearance, cautions, _ = self._review(final_bucket="urgente")
        assert clearance is True
        assert any("URGENTE" in c for c in cautions)

    def test_fiebre_requiere_autorizacion(self):
        clearance, cautions, _ = self._review(fever=True)
        assert clearance is True
        assert any("fiebre" in c.lower() for c in cautions)

    def test_fc_reposo_alta_requiere_autorizacion(self):
        assert self._review(avg_resting_hr=95.0)[0] is True
        assert self._review(high_resting_hr_days=6)[0] is True

    def test_antecedente_cardiaco_requiere_autorizacion(self):
        clearance, cautions, _ = self._review(chronic_notes="infarto hace 2 anos")
        assert clearance is True
        assert any("infarto" in c for c in cautions)

    def test_obesidad_extrema_limita_impacto(self):
        clearance, _, restrictions = self._review(bmi=42.0)
        assert clearance is True
        assert any("impacto" in r.lower() for r in restrictions)

    def test_problema_articular_solo_adapta(self):
        clearance, _, restrictions = self._review(chronic_notes="artrosis de rodilla")
        assert clearance is False
        assert any("saltos" in r.lower() for r in restrictions)

    def test_diabetes_e_hipertension_generan_adaptaciones(self):
        _, _, restrictions = self._review(chronic_notes="diabetes tipo 2 e hipertension")
        texto = " ".join(restrictions).lower()
        assert "glucemia" in texto and "valsalva" in texto

    def test_alerta_de_laboratorio_escala_a_autorizacion(self):
        clearance, cautions, _ = self._review(
            lab_alerts=["Anemia significativa (Hb < 10 g/dL): evitar ejercicio intenso."]
        )
        assert clearance is True
        assert cautions


# ---------------------------------------------------------------------------
# Plan completo
# ---------------------------------------------------------------------------

class TestFullPlan:

    def test_plan_completo_de_paciente_con_riesgo(self):
        plan = build_lifestyle_plan(
            patient=PatientInfo(name="Juan Test", age=58, sex="M"),
            q=_questionnaire(chronic="hipertension", ex_days=1, rested=2),
            anthro={"weight_kg": 98.0, "height_cm": 174.0, "waist_cm": 112.0},
            w30=_wearable(steps=3200.0, ex_min=8.0, sleep=5.5, low_sleep=14),
            lab_data={"bioquimica": {"glucosa_mg_dl": 118, "colesterol_ldl_mg_dl": 155}},
            final_bucket="7_dias",
        )
        assert plan.bmi_category.startswith("Obesidad")
        assert plan.waist_category == "Riesgo muy aumentado"
        assert plan.nutrition.energy.objective == "perder_peso"
        assert plan.exercise.weekly_min_target == WHO_AEROBIC_WEIGHT
        assert any("hipertension" in r.lower() for r in plan.exercise.restrictions)
        assert any("Perder" in g for g in plan.goals)
        assert any("circunferencia abdominal" in g.lower() for g in plan.goals)
        assert any("Dormir" in g for g in plan.goals)

    def test_acepta_diccionarios_ademas_de_dataclasses(self):
        plan = build_lifestyle_plan(
            patient={"name": "Ana", "age": 42, "sex": "F"},
            q={"diet_style": "vegetariana", "other_notes": "", "exercise_days_last_weeks": 2},
            anthro={"weight_kg": 62.0, "height_cm": 165.0, "waist_cm": 78.0},
            w30={"avg_steps": 7000, "avg_exercise_min": 20, "avg_resting_hr": 64,
                 "low_sleep_days": 3, "high_resting_hr_days": 0, "days": 30},
        )
        assert "Vegetariana" in plan.nutrition.pattern
        assert plan.nutrition.energy.objective == "mantener"

    def test_render_incluye_todas_las_secciones(self):
        plan = build_lifestyle_plan(
            patient=PatientInfo(name="Test", age=45, sex="F"),
            q=_questionnaire(),
            anthro={"weight_kg": 78.0, "height_cm": 162.0, "waist_cm": 92.0},
            w30=_wearable(),
        )
        texto = render_plan_text(plan)
        for seccion in ["PACIENTE", "BALANCE ENERGETICO", "ALIMENTACION",
                        "EJERCICIO", "OBJETIVOS DE SEGUIMIENTO"]:
            assert seccion in texto
        assert "No sustituye la valoracion medica" in texto

    def test_render_avisa_de_autorizacion_medica(self):
        plan = build_lifestyle_plan(
            patient=PatientInfo(name="Test", age=70, sex="M"),
            q=_questionnaire(fever=True),
            anthro={"weight_kg": 88.0, "height_cm": 170.0},
            w30=_wearable(),
            final_bucket="urgente",
        )
        assert plan.medical_clearance is True
        assert "REQUIERE AUTORIZACION MEDICA" in render_plan_text(plan)
