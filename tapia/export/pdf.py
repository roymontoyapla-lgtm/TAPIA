# -*- coding: utf-8 -*-
"""
Exportacion del informe a PDF con ReportLab.
Version mejorada con cabecera corporativa, tabla de metricas y semaforo de urgencia.
"""

import logging
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
        HRFlowable, KeepTogether,
    )
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    REPORTLAB_OK = True
except ImportError:
    REPORTLAB_OK = False
    logger.warning("ReportLab no instalado. PDF no disponible.")

# Paleta de colores TAPIA
_RED    = colors.HexColor("#c0392b")
_ORANGE = colors.HexColor("#e67e22")
_GREEN  = colors.HexColor("#27ae60")
_BLUE   = colors.HexColor("#2c3e50")
_LIGHT  = colors.HexColor("#f8f9fa")
_GRAY   = colors.HexColor("#7f8c8d")
_WHITE  = colors.white

_BUCKET_COLOR = {
    "urgente":   _RED,
    "7_dias":    _ORANGE,
    "2_semanas": _GREEN,
}
_BUCKET_LABEL = {
    "urgente":   "URGENTE",
    "7_dias":    "Dentro de los proximos 7 dias",
    "2_semanas": "En un periodo de 2 semanas",
}


def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("title", fontSize=20, fontName="Helvetica-Bold",
                                textColor=_BLUE, spaceAfter=2),
        "subtitle": ParagraphStyle("subtitle", fontSize=10, fontName="Helvetica",
                                   textColor=_GRAY, spaceAfter=8),
        "section": ParagraphStyle("section", fontSize=11, fontName="Helvetica-Bold",
                                  textColor=_BLUE, spaceBefore=10, spaceAfter=4),
        "body": ParagraphStyle("body", fontSize=9, fontName="Helvetica",
                               textColor=colors.black, spaceAfter=3, leading=13),
        "small": ParagraphStyle("small", fontSize=8, fontName="Helvetica",
                                textColor=_GRAY, spaceAfter=2),
        "badge": ParagraphStyle("badge", fontSize=13, fontName="Helvetica-Bold",
                                textColor=_WHITE, alignment=TA_CENTER),
        "disclaimer": ParagraphStyle("disclaimer", fontSize=8, fontName="Helvetica-Oblique",
                                     textColor=_GRAY, alignment=TA_CENTER),
    }


def _header(styles, patient_name: str, patient_age: int, patient_sex: str) -> list:
    """Cabecera con nombre de app, datos del paciente y fecha."""
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    elements = []

    # Tabla de cabecera: logo/titulo | datos paciente | fecha
    header_data = [[
        Paragraph("TAPIA", styles["title"]),
        Paragraph(
            f"<b>Paciente:</b> {patient_name}<br/>"
            f"<b>Edad:</b> {patient_age} anos &nbsp;&nbsp; <b>Sexo:</b> {patient_sex}",
            styles["body"]
        ),
        Paragraph(f"<b>Fecha:</b> {now}", styles["body"]),
    ]]
    t = Table(header_data, colWidths=[5*cm, 9*cm, 4*cm])
    t.setStyle(TableStyle([
        ("VALIGN",       (0,0), (-1,-1), "MIDDLE"),
        ("BACKGROUND",   (0,0), (-1,-1), _LIGHT),
        ("ROUNDEDCORNERS", [6]),
        ("BOTTOMPADDING",(0,0), (-1,-1), 8),
        ("TOPPADDING",   (0,0), (-1,-1), 8),
        ("LEFTPADDING",  (0,0), (-1,-1), 10),
    ]))
    elements.append(t)
    elements.append(Paragraph(
        "Triaje Automatizado por IA - Informe orientativo",
        styles["subtitle"]
    ))
    elements.append(HRFlowable(width="100%", thickness=1, color=_BLUE))
    elements.append(Spacer(1, 0.3*cm))
    return elements


def _urgency_badge(styles, final_bucket: str, local_score: int,
                   local_bucket: str, ai_bucket: str) -> list:
    """Bloque visual de prioridad con semaforo."""
    color = _BUCKET_COLOR.get(final_bucket, _GRAY)
    label = _BUCKET_LABEL.get(final_bucket, final_bucket)
    local_label = _BUCKET_LABEL.get(local_bucket, local_bucket)
    ai_label    = _BUCKET_LABEL.get(ai_bucket,    ai_bucket)

    badge = Table(
        [[Paragraph(f"PRIORIDAD FINAL: {label}", styles["badge"])]],
        colWidths=[17*cm],
    )
    badge.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,-1), color),
        ("ROUNDEDCORNERS",[8]),
        ("TOPPADDING",    (0,0), (-1,-1), 10),
        ("BOTTOMPADDING", (0,0), (-1,-1), 10),
    ]))

    detail = Table([
        [
            Paragraph(f"<b>Score local:</b> {local_score}  |  {local_label}", styles["body"]),
            Paragraph(f"<b>Prioridad IA:</b> {ai_label}", styles["body"]),
        ]
    ], colWidths=[8.5*cm, 8.5*cm])
    detail.setStyle(TableStyle([
        ("BACKGROUND",   (0,0), (-1,-1), _LIGHT),
        ("TOPPADDING",   (0,0), (-1,-1), 5),
        ("BOTTOMPADDING",(0,0), (-1,-1), 5),
        ("LEFTPADDING",  (0,0), (-1,-1), 8),
    ]))

    return [badge, Spacer(1, 0.2*cm), detail, Spacer(1, 0.4*cm)]


def _metrics_table(styles, w30_data: Dict[str, Any]) -> list:
    """Tabla de metricas del wearable con colores segun umbrales."""
    def v(val, unit=""): return f"{val}{unit}" if val is not None else "N/D"

    rows = [
        ["Metrica", "Valor", "Referencia"],
        ["FC reposo media",      v(w30_data.get("avg_resting_hr"), " bpm"), "< 90 bpm"],
        ["Pasos medios/dia",     v(w30_data.get("avg_steps")),              "> 3.000 pasos"],
        ["Sueno medio",          v(w30_data.get("avg_sleep_h"), " h"),      ">= 6 h/noche"],
        ["Ejercicio medio",      v(w30_data.get("avg_exercise_min"), " min"),"30+ min/dia"],
        ["Dias sueno < 6h",      str(w30_data.get("low_sleep_days", 0)),    "< 8 dias/mes"],
        ["Dias < 3.000 pasos",   str(w30_data.get("very_low_activity_days",0)), "< 8 dias/mes"],
        ["Dias FC reposo >= 90", str(w30_data.get("high_resting_hr_days", 0)), "0 dias"],
    ]

    t = Table(rows, colWidths=[7*cm, 5*cm, 5*cm])
    style = [
        # Cabecera
        ("BACKGROUND",   (0,0), (-1,0), _BLUE),
        ("TEXTCOLOR",    (0,0), (-1,0), _WHITE),
        ("FONTNAME",     (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE",     (0,0), (-1,-1), 9),
        ("ALIGN",        (1,0), (-1,-1), "CENTER"),
        ("VALIGN",       (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING",   (0,0), (-1,-1), 5),
        ("BOTTOMPADDING",(0,0), (-1,-1), 5),
        ("LEFTPADDING",  (0,0), (-1,-1), 8),
        ("GRID",         (0,0), (-1,-1), 0.5, colors.HexColor("#dfe6e9")),
        # Filas alternas
        *[("BACKGROUND", (0,i), (-1,i), _LIGHT) for i in range(2, len(rows), 2)],
    ]
    t.setStyle(TableStyle(style))
    return [t, Spacer(1, 0.4*cm)]


def _text_section(styles, title: str, lines: list) -> list:
    elements = [Paragraph(title, styles["section"])]
    for line in lines:
        if line.strip():
            elements.append(Paragraph(f"- {line}", styles["body"]))
    return elements


def save_pdf(
    filename: str,
    report_text: str,
    patient_name: str = "N/D",
    patient_age: int = 0,
    patient_sex: str = "N/D",
    final_bucket: str = "2_semanas",
    local_score: int = 0,
    local_bucket: str = "2_semanas",
    ai_bucket: str = "2_semanas",
    ai_justification: str = "",
    ai_red_flags: list = None,
    w30_data: Dict[str, Any] = None,
    reasons: list = None,
    local_motivos: list = None,
) -> None:
    """Genera el PDF mejorado con cabecera, semaforo y tabla de metricas."""
    if not REPORTLAB_OK:
        raise RuntimeError("ReportLab no esta instalado.\nInstala con: pip install reportlab")

    if ai_red_flags   is None: ai_red_flags   = []
    if w30_data       is None: w30_data        = {}
    if reasons        is None: reasons         = []
    if local_motivos  is None: local_motivos   = []

    doc = SimpleDocTemplate(
        filename,
        pagesize=A4,
        rightMargin=2*cm, leftMargin=2*cm,
        topMargin=2*cm,   bottomMargin=2*cm,
    )
    styles   = _styles()
    elements = []

    # Cabecera
    elements += _header(styles, patient_name, patient_age, patient_sex)

    # Semaforo de urgencia
    elements += _urgency_badge(styles, final_bucket, local_score, local_bucket, ai_bucket)

    # Tabla de metricas wearable
    if w30_data:
        elements.append(Paragraph("Metricas del wearable (ultimo mes)", styles["section"]))
        elements += _metrics_table(styles, w30_data)

    # Motivos AP / especialista
    if reasons:
        elements += _text_section(styles, "AP vs Especialista", reasons[:6])
        elements.append(Spacer(1, 0.2*cm))

    # Motivos score
    if local_motivos:
        elements += _text_section(styles, "Factores del score de urgencia", local_motivos[:8])
        elements.append(Spacer(1, 0.2*cm))

    # Justificacion IA
    if ai_justification or ai_red_flags:
        elements.append(Paragraph("Evaluacion de la IA", styles["section"]))
        if ai_justification:
            elements.append(Paragraph(ai_justification, styles["body"]))
        if ai_red_flags:
            elements.append(Paragraph("<b>Banderas rojas:</b>", styles["body"]))
            for rf in ai_red_flags:
                elements.append(Paragraph(f"  - {rf}", styles["body"]))
        elements.append(Spacer(1, 0.2*cm))

    # Informe completo
    elements.append(HRFlowable(width="100%", thickness=0.5, color=_GRAY))
    elements.append(Spacer(1, 0.2*cm))
    elements.append(Paragraph("Informe completo", styles["section"]))

    def esc(s):
        return s.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

    for line in report_text.split("\n"):
        if line.strip():
            elements.append(Paragraph(esc(line), styles["body"]))
        else:
            elements.append(Spacer(1, 0.2*cm))

    # Disclaimer
    elements.append(Spacer(1, 0.5*cm))
    elements.append(HRFlowable(width="100%", thickness=0.5, color=_GRAY))
    elements.append(Spacer(1, 0.2*cm))
    elements.append(Paragraph(
        "Aviso: Este informe es meramente orientativo y no sustituye la valoracion clinica "
        "de un profesional sanitario. TAPIA v1.2 - Triaje Automatizado por IA.",
        styles["disclaimer"]
    ))

    doc.build(elements)
    logger.info("PDF mejorado guardado en: %s", filename)
