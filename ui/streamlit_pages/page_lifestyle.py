# -*- coding: utf-8 -*-
"""
Pagina de plan de alimentacion y ejercicio.

Reune todo lo que TAPIA ya sabe del paciente (antropometria, wearable,
analisis clinicos y ultimo triaje), calcula un plan deterministico con
core.lifestyle y permite redactarlo con IA para entregarselo al paciente.
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime
from typing import Any, Dict, List, Optional

import streamlit as st

from ...ai.lifestyle_client import generate_ai_lifestyle_plan
from ...auth.auth import has_permission
from ...compliance.audit import Action, log
from ...core.anthropometry import compute_bmi, bmi_category, waist_risk_category
from ...core.lifestyle import build_lifestyle_plan, render_plan_text
from ...core.wearable import filter_by_days, summarize
from ...db import database as db
from ..session import init

try:
    from ...export.pdf import REPORTLAB_OK, save_pdf
except Exception:            # pragma: no cover - reportlab opcional
    REPORTLAB_OK = False


def _wearable_summary(patient_id: int, days: int = 30):
    """Resumen del wearable de los ultimos `days` dias, o None si no hay datos."""
    records = db.get_wearable_history(patient_id)
    if not records:
        return None, 0
    window = filter_by_days(records, days)
    if not window:
        return None, len(records)
    return summarize(window), len(records)


def _anthro_form(latest: Optional[Dict[str, Any]], sex: str) -> Dict[str, Any]:
    """Formulario de medidas, precargado con la ultima medida registrada."""
    st.markdown("**Medidas actuales**")
    c1, c2, c3 = st.columns(3)
    with c1:
        weight = st.number_input(
            "Peso (kg)", min_value=0.0, max_value=400.0, step=0.5,
            value=float(latest.get("weight_kg") or 0.0) if latest else 0.0,
        )
    with c2:
        height = st.number_input(
            "Altura (cm)", min_value=0.0, max_value=250.0, step=1.0,
            value=float(latest.get("height_cm") or 0.0) if latest else 0.0,
        )
    with c3:
        waist = st.number_input(
            "Circunferencia abdominal (cm)", min_value=0.0, max_value=250.0, step=1.0,
            value=float(latest.get("waist_cm") or 0.0) if latest else 0.0,
        )

    weight_v = weight if weight > 0 else None
    height_v = height if height > 0 else None
    waist_v  = waist  if waist  > 0 else None
    bmi = compute_bmi(weight_v, height_v)
    return {
        "weight_kg": weight_v,
        "height_cm": height_v,
        "waist_cm":  waist_v,
        "bmi": bmi,
        "bmi_category": bmi_category(bmi),
        "waist_category": waist_risk_category(waist_v, sex),
    }


def _show_plan(plan) -> None:
    """Muestra el plan calculado en pestanas."""
    n, e = plan.nutrition, plan.exercise
    en = n.energy

    if plan.medical_clearance:
        st.error(
            "Este paciente requiere **autorizacion medica** antes de iniciar el "
            "programa de ejercicio. Hasta entonces el plan se limita a actividad ligera."
        )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("IMC", plan.bmi if plan.bmi is not None else "N/D", plan.bmi_category, delta_color="off")
    c2.metric("Ingesta objetivo", f"{en.target_kcal} kcal" if en.target_kcal else "N/D",
              en.objective_label, delta_color="off")
    c3.metric("Ejercicio objetivo", f"{e.weekly_min_target} min/sem",
              f"inicio: {e.weekly_min_start} min/sem", delta_color="off")
    c4.metric("Pasos objetivo", f"{e.steps_goal}/dia",
              f"actual: {e.baseline_steps}" if e.baseline_steps is not None else "sin wearable",
              delta_color="off")

    tab1, tab2, tab3, tab4 = st.tabs(
        ["Alimentacion", "Ejercicio", "Seguridad y objetivos", "Informe completo"]
    )

    with tab1:
        st.markdown(f"**Patron:** {n.pattern}")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Proteina", f"{n.protein_g} g" if n.protein_g else "N/D")
        m2.metric("Hidratos", f"{n.carbs_g} g" if n.carbs_g else "N/D")
        m3.metric("Grasas",   f"{n.fat_g} g"   if n.fat_g   else "N/D")
        m4.metric("Fibra",    f"{n.fiber_g} g")
        st.caption(
            f"Agua: {n.water_ml} ml/dia | Sal: maximo {n.salt_g_max:.0f} g/dia"
            + (f" | {n.protein_note}" if n.protein_note else "")
        )

        st.markdown("**Prioridades**")
        for p in n.priorities:
            st.markdown(f"- {p}")

        cA, cB = st.columns(2)
        with cA:
            st.markdown("**Priorizar**")
            for f in n.prefer:
                st.markdown(f"- {f}")
        with cB:
            st.markdown("**Limitar**")
            for f in n.limit:
                st.markdown(f"- {f}")

        st.markdown("**Ejemplo de dia**")
        for meal, content in n.sample_day:
            st.markdown(f"- **{meal}:** {content}")

        st.markdown("**Habitos**")
        for h in n.habits:
            st.markdown(f"- {h}")

    with tab2:
        st.markdown(
            f"**Punto de partida:** {e.baseline_weekly_min} min/semana"
            + (f" y {e.baseline_steps} pasos/dia" if e.baseline_steps is not None else "")
        )
        st.markdown(f"**Intensidad:** {e.intensity}")
        st.markdown(
            f"**Inicio:** {e.weekly_min_start} min/semana en {e.sessions_per_week} "
            f"sesiones de {e.minutes_per_session} min | **Fuerza:** {e.strength_sessions} dias/semana"
            + (f" | **Equilibrio:** {e.balance_sessions} dias/semana" if e.balance_sessions else "")
        )

        st.markdown("**Semana tipo**")
        st.table({"Dia": [d for d, _ in e.weekly_schedule],
                  "Sesion": [t for _, t in e.weekly_schedule]})

        st.markdown("**Progresion**")
        for p in e.progression:
            st.markdown(f"- {p}")

        if e.restrictions:
            st.markdown("**Adaptaciones**")
            for r in e.restrictions:
                st.markdown(f"- {r}")

    with tab3:
        if plan.cautions:
            st.markdown("**Avisos de seguridad**")
            for c in plan.cautions:
                st.warning(c)
        else:
            st.success("No se han detectado contraindicaciones en los datos disponibles.")

        st.markdown("**Objetivos de seguimiento**")
        for g in plan.goals:
            st.markdown(f"- {g}")
        st.caption("Datos utilizados: " + ", ".join(plan.data_used))

    with tab4:
        st.code(render_plan_text(plan), language=None)


def _downloads(text: str, patient_name: str, suffix: str = "plan") -> None:
    """Botones de descarga en txt y pdf."""
    fname = (
        f"tapia_{suffix}_{patient_name.replace(' ', '_') or 'paciente'}"
        f"_{datetime.now().strftime('%Y%m%d_%H%M')}"
    )
    c1, c2 = st.columns(2)
    with c1:
        st.download_button(
            "Descargar (.txt)", data=text.encode("utf-8"),
            file_name=f"{fname}.txt", mime="text/plain",
            key=f"dl_txt_{suffix}",
        )
    with c2:
        if not REPORTLAB_OK:
            st.info("Instala reportlab para habilitar la descarga en PDF.")
            return
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            save_pdf(
                tmp_path, text,
                patient_name=patient_name or "Paciente",
                show_urgency=False,
                section_title="Plan de alimentacion y ejercicio",
            )
            with open(tmp_path, "rb") as f:
                st.download_button(
                    "Descargar (.pdf)", data=f.read(),
                    file_name=f"{fname}.pdf", mime="application/pdf",
                    key=f"dl_pdf_{suffix}",
                )
        except Exception as e:
            st.warning(f"No se pudo generar el PDF: {e}")
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)


def run() -> None:
    init()
    db.init_db()

    header = st.session_state.get("page_header")
    if header:
        header("Plan de alimentacion y ejercicio")
    else:
        st.title("Plan de alimentacion y ejercicio")

    role = st.session_state.get("role", "consultor")
    if not has_permission(role, "lifestyle"):
        st.error("No tienes permiso para acceder a esta seccion.")
        return

    st.caption(
        "Calcula un plan nutricional y de ejercicio a partir de la antropometria, "
        "el wearable y los analisis del paciente, siguiendo las directrices de la OMS. "
        "Es orientativo y no sustituye la valoracion medica ni la de un dietista-nutricionista."
    )

    patients = db.list_patients()
    if not patients:
        st.info("No hay pacientes registrados. Ejecuta al menos un triaje primero.")
        return

    options = {f"{p['name']} ({p['age']} anos, {p['sex']})": p for p in patients}
    selected = st.selectbox("Selecciona un paciente", list(options.keys()))
    patient = options[selected]
    patient_id = patient["id"]

    w30, total_days = _wearable_summary(patient_id, days=30)
    latest_lab   = db.get_latest_lab(patient_id)
    latest_anthro = db.get_latest_anthropometry(patient_id)
    triages = db.get_by_patient(patient_id)
    last_bucket = triages[0].final_bucket if triages else "2_semanas"

    c1, c2, c3 = st.columns(3)
    c1.metric("Dias de wearable", total_days)
    c2.metric("Analisis clinicos", len(db.get_lab_results(patient_id)))
    c3.metric("Ultimo triaje", last_bucket.replace("_", " ") if triages else "sin triajes")

    st.divider()

    with st.form("lifestyle_form"):
        anthro = _anthro_form(latest_anthro, patient.get("sex", ""))

        st.markdown("**Preferencias y condicionantes**")
        c1, c2 = st.columns(2)
        with c1:
            diet_style = st.text_input(
                "Estilo de alimentacion",
                placeholder="mediterranea, vegetariana, vegana, sin gluten...",
            )
            allergies = st.text_input(
                "Alergias o intolerancias",
                placeholder="lactosa, frutos secos... (vacio si ninguna)",
            )
        with c2:
            chronic = st.text_input(
                "Enfermedades cronicas o limitaciones",
                placeholder="hipertension, diabetes, artrosis de rodilla...",
            )
            preferences = st.text_input(
                "Gustos y disponibilidad",
                placeholder="no le gusta el pescado, cocina poco, gimnasio 3 dias...",
            )

        c3, c4 = st.columns(2)
        with c3:
            ex_days = st.number_input(
                "Dias de ejercicio por semana (si no hay wearable)",
                min_value=0, max_value=7, value=0, step=1,
            )
        with c4:
            use_ai = st.checkbox(
                "Redactar el plan para el paciente con IA", value=False,
                help="El calculo lo hace siempre TAPIA. La IA solo lo redacta de forma cercana.",
            )

        submitted = st.form_submit_button(
            "Calcular plan", type="primary", use_container_width=True
        )

    if submitted:
        q = {
            "diet_style": diet_style,
            "other_notes": chronic,
            "fever": False,
            "exercise_days_last_weeks": int(ex_days) if ex_days else None,
            "rested_enough": None,
        }
        plan = build_lifestyle_plan(
            patient=patient,
            q=q,
            anthro=anthro,
            w30=w30,
            lab_data=(latest_lab or {}).get("data"),
            final_bucket=last_bucket,
        )
        plan_text = render_plan_text(plan)

        # Persistir la medida antropometrica para el historico del paciente
        db.save_anthropometry(
            patient_id=patient_id,
            weight_kg=anthro["weight_kg"], height_cm=anthro["height_cm"],
            waist_cm=anthro["waist_cm"], bmi=anthro["bmi"],
            bmi_category=anthro["bmi_category"], waist_category=anthro["waist_category"],
        )

        ai_result = {"text": "", "model": "", "ok": False, "error": ""}
        if use_ai:
            with st.spinner("La IA esta redactando el plan del paciente..."):
                ai_result = generate_ai_lifestyle_plan(
                    plan, preferences=preferences, allergies=allergies, notes=chronic,
                )

        db.save_lifestyle_plan(
            patient_id=patient_id,
            plan_text=plan_text,
            objective=plan.nutrition.energy.objective,
            target_kcal=plan.nutrition.energy.target_kcal,
            weekly_min=plan.exercise.weekly_min_target,
            steps_goal=plan.exercise.steps_goal,
            clearance=plan.medical_clearance,
            ai_text=ai_result.get("text", ""),
            ai_model=ai_result.get("model", ""),
        )
        log(
            Action.LIFESTYLE_PLAN,
            patient_id=patient_id,
            ai_model=ai_result.get("model", ""),
            details=(
                f"objetivo={plan.nutrition.energy.objective};"
                f"kcal={plan.nutrition.energy.target_kcal};"
                f"min_semana={plan.exercise.weekly_min_target};"
                f"autorizacion_medica={plan.medical_clearance}"
            ),
        )

        st.session_state["lifestyle_plan_text"] = plan_text
        st.session_state["lifestyle_plan_obj"]  = plan
        st.session_state["lifestyle_ai"]        = ai_result
        st.session_state["lifestyle_patient"]   = patient.get("name", "Paciente")

    # -----------------------------------------------------------------------
    # Resultado
    # -----------------------------------------------------------------------
    plan = st.session_state.get("lifestyle_plan_obj")
    if plan is None:
        st.info("Rellena las medidas y pulsa **Calcular plan**.")
        _show_history(patient_id)
        return

    st.divider()
    st.subheader("Plan calculado")
    _show_plan(plan)
    _downloads(st.session_state["lifestyle_plan_text"],
               st.session_state.get("lifestyle_patient", "paciente"))

    ai_result = st.session_state.get("lifestyle_ai") or {}
    if ai_result.get("ok"):
        st.divider()
        st.subheader("Plan redactado para el paciente")
        st.caption(f"Redactado con {ai_result.get('model','IA')} sobre las cifras calculadas por TAPIA.")
        st.markdown(ai_result["text"])
        _downloads(ai_result["text"],
                   st.session_state.get("lifestyle_patient", "paciente"),
                   suffix="plan_paciente")
    elif ai_result.get("error"):
        st.warning(f"No se pudo redactar el plan con IA: {ai_result['error']}")

    _show_history(patient_id)


def _show_history(patient_id: int) -> None:
    """Lista los planes anteriores guardados del paciente."""
    previous = db.get_lifestyle_plans(patient_id, limit=10)
    if not previous:
        return
    st.divider()
    with st.expander(f"Planes anteriores ({len(previous)})"):
        for p in previous:
            title = (
                f"{p['created_at'][:16].replace('T',' ')} - "
                f"{p.get('objective','')} - {p.get('target_kcal') or 'N/D'} kcal - "
                f"{p.get('weekly_min') or 'N/D'} min/semana"
            )
            st.markdown(f"**{title}**")
            if p.get("clearance"):
                st.caption("Requeria autorizacion medica previa.")
            st.code(p["plan_text"][:1500] + ("..." if len(p["plan_text"]) > 1500 else ""),
                    language=None)
