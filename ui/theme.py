# -*- coding: utf-8 -*-
"""
Tema visual de TAPIA: tipografia del sistema, superficies claras y acentos
sobrios, al estilo de las interfaces de Apple.

Streamlit solo deja configurar cuatro colores en config.toml, asi que el
resto se aplica como CSS desde `inject()`, que se llama una vez al arrancar
la aplicacion.

Todo lo que se toca aqui es apariencia: si un selector dejara de coincidir
tras una actualizacion de Streamlit, la pagina seguiria funcionando.
"""

from __future__ import annotations

import streamlit as st

# ---------------------------------------------------------------------------
# Paleta
# ---------------------------------------------------------------------------

FONDO        = "#ffffff"
FONDO_SUAVE  = "#f5f5f7"   # gris de las superficies secundarias
TEXTO        = "#1d1d1f"
TEXTO_SUAVE  = "#6e6e73"
ACENTO       = "#0071e3"   # azul de accion
BORDE        = "rgba(0, 0, 0, 0.08)"

# Colores de urgencia: tonos oscuros para que el texto blanco encima
# mantenga contraste suficiente (los tonos vivos de iOS no lo cumplen).
URGENCIA = {
    "urgente":   "#d70015",
    "7_dias":    "#b45309",
    "2_semanas": "#15803d",
}

# Pila tipografica: SF Pro en Apple, Segoe UI en Windows, Roboto en Android
FUENTE = ('-apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", '
          '"Helvetica Neue", "Segoe UI", Roboto, Ubuntu, sans-serif')


def _css() -> str:
    return f"""
<style>
:root {{
  --tapia-fondo:       {FONDO};
  --tapia-fondo-suave: {FONDO_SUAVE};
  --tapia-texto:       {TEXTO};
  --tapia-texto-suave: {TEXTO_SUAVE};
  --tapia-acento:      {ACENTO};
  --tapia-borde:       {BORDE};
  --tapia-radio:       14px;
  --tapia-sombra:      0 1px 2px rgba(0,0,0,.04), 0 8px 24px rgba(0,0,0,.06);
}}

/* --- Tipografia ------------------------------------------------------- */
html, body, [class*="st-"], button, input, textarea, select, [data-testid] {{
  font-family: {FUENTE} !important;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}}

/* Los iconos de Streamlit son ligaduras de una fuente propia: la regla
   anterior se los llevaba por delante y se veian como texto ("visibility"). */
[data-testid="stIconMaterial"], .material-icons, .material-symbols-rounded,
span[class*="material-symbols"], span[class*="material-icons"] {{
  font-family: "Material Symbols Rounded", "Material Symbols Outlined",
               "Material Icons" !important;
}}

h1, h2, h3, h4 {{ color: var(--tapia-texto); }}
h1 {{ font-size: 2.6rem !important; font-weight: 600 !important;
     letter-spacing: -.022em !important; line-height: 1.08 !important; }}
h2 {{ font-size: 1.7rem !important; font-weight: 600 !important;
     letter-spacing: -.02em !important; }}
h3 {{ font-size: 1.25rem !important; font-weight: 600 !important;
     letter-spacing: -.015em !important; }}

/* --- Lienzo ----------------------------------------------------------- */
[data-testid="stAppViewContainer"] {{ background: var(--tapia-fondo); }}
[data-testid="stHeader"] {{ background: transparent; }}
[data-testid="stAppDeployButton"] {{ display: none; }}

[data-testid="stAppViewContainer"] .block-container {{
  padding-top: 2.6rem;
  padding-bottom: 4rem;
  max-width: 1140px;
}}

/* --- Barra lateral ---------------------------------------------------- */
section[data-testid="stSidebar"] {{
  background: var(--tapia-fondo-suave);
  border-right: 1px solid var(--tapia-borde);
}}
section[data-testid="stSidebar"] .block-container {{ padding-top: 2rem; }}

/* Navegacion: la lista de radios se presenta como un menu.
   Se usan data-testid y data-selected, que Streamlit mantiene estables,
   en vez de las clases generadas (st-emotion-cache-...), que cambian. */
section[data-testid="stSidebar"] div[role="radiogroup"] {{ gap: 2px; }}
section[data-testid="stSidebar"] label[data-testid="stRadioOption"] {{
  border-radius: 10px;
  padding: 8px 12px;
  margin: 0;
  cursor: pointer;
  transition: background .15s ease;
}}
section[data-testid="stSidebar"] label[data-testid="stRadioOption"]:hover {{
  background: rgba(0,0,0,.05);
}}
/* El circulo del radio sobra: la seleccion se ve por el fondo */
section[data-testid="stSidebar"] label[data-testid="stRadioOption"] > div > div > div:first-child {{
  display: none !important;
}}
section[data-testid="stSidebar"] label[data-testid="stRadioOption"][data-selected="true"] {{
  background: var(--tapia-fondo);
  box-shadow: 0 1px 2px rgba(0,0,0,.08);
}}
section[data-testid="stSidebar"] label[data-testid="stRadioOption"][data-selected="true"] p {{
  font-weight: 600 !important;
  color: var(--tapia-texto) !important;
}}
section[data-testid="stSidebar"] label[data-testid="stRadioOption"] p {{
  color: var(--tapia-texto) !important;
}}

/* --- Botones ---------------------------------------------------------- */
.stButton > button,
.stDownloadButton > button,
[data-testid="stFormSubmitButton"] > button {{
  border-radius: 980px !important;
  border: 1px solid var(--tapia-borde) !important;
  font-weight: 500 !important;
  padding: .5rem 1.25rem !important;
  transition: transform .12s ease, filter .12s ease, background .12s ease;
}}
.stButton > button:active,
.stDownloadButton > button:active,
[data-testid="stFormSubmitButton"] > button:active {{ transform: scale(.98); }}

button[kind="primary"], button[kind="primaryFormSubmit"] {{
  background: var(--tapia-acento) !important;
  border-color: var(--tapia-acento) !important;
  color: #fff !important;
}}
button[kind="primary"]:hover, button[kind="primaryFormSubmit"]:hover {{
  filter: brightness(1.08);
}}
button[kind="secondary"], button[kind="secondaryFormSubmit"] {{
  background: var(--tapia-fondo) !important;
  color: var(--tapia-texto) !important;
}}
button[kind="secondary"]:hover {{ background: var(--tapia-fondo-suave) !important; }}

/* --- Campos ----------------------------------------------------------- */
[data-testid="stTextInput"] input,
[data-testid="stNumberInput"] input,
[data-testid="stTextArea"] textarea,
[data-testid="stSelectbox"] div[data-baseweb="select"] > div,
[data-testid="stSelectbox"] div[data-baseweb="select"] div[role="combobox"] {{
  border-radius: 10px !important;
  background: var(--tapia-fondo) !important;
  border: 1px solid var(--tapia-borde) !important;
  color: var(--tapia-texto) !important;
}}
[data-testid="stTextInput"] input:focus,
[data-testid="stNumberInput"] input:focus,
[data-testid="stTextArea"] textarea:focus {{
  border-color: var(--tapia-acento) !important;
  box-shadow: 0 0 0 4px rgba(0,113,227,.15) !important;
}}
[data-testid="stNumberInput"] button {{
  background: var(--tapia-fondo) !important;
  border-left: 1px solid var(--tapia-borde) !important;
}}
[data-testid="stFileUploaderDropzone"] {{
  border-radius: var(--tapia-radio) !important;
  border: 1px dashed var(--tapia-borde) !important;
  background: var(--tapia-fondo-suave) !important;
}}

/* --- Superficies: formularios, desplegables, metricas ------------------ */
[data-testid="stForm"] {{
  border: none !important;
  border-radius: 18px !important;
  background: var(--tapia-fondo);
  box-shadow: var(--tapia-sombra);
  padding: 1.5rem 1.75rem !important;
}}
[data-testid="stExpander"] {{
  border: none !important;
  border-radius: var(--tapia-radio) !important;
  background: var(--tapia-fondo-suave);
  box-shadow: none;
}}
[data-testid="stExpander"] summary {{ font-weight: 500; }}

[data-testid="stMetric"] {{
  background: var(--tapia-fondo);
  border: 1px solid var(--tapia-borde);
  border-radius: var(--tapia-radio);
  padding: 14px 16px;
}}
[data-testid="stMetricValue"] {{
  font-weight: 600 !important;
  letter-spacing: -.02em !important;
}}
[data-testid="stMetricLabel"] p {{ color: var(--tapia-texto-suave) !important; }}

/* --- Avisos ----------------------------------------------------------- */
[data-testid="stAlert"] {{
  border-radius: var(--tapia-radio) !important;
  border: none !important;
}}

/* --- Pestanas --------------------------------------------------------- */
[data-testid="stTabs"] [data-baseweb="tab-list"] {{
  gap: 4px;
  border-bottom: 1px solid var(--tapia-borde);
}}
[data-testid="stTabs"] [data-baseweb="tab"] {{
  border-radius: 8px 8px 0 0;
  padding: 8px 14px;
  font-weight: 500;
}}
[data-testid="stTabs"] [aria-selected="true"] {{ color: var(--tapia-acento) !important; }}

/* --- Movil ------------------------------------------------------------ */
/* Streamlit ya apila las columnas solo; aqui se ajustan tamanos y margenes
   para que quepa el contenido sin zoom. */
@media (max-width: 640px) {{
  [data-testid="stAppViewContainer"] .block-container {{
    padding-top: 1.25rem;
    padding-left: 1rem;
    padding-right: 1rem;
    padding-bottom: 2.5rem;
  }}
  h1 {{ font-size: 1.9rem !important; line-height: 1.15 !important; }}
  h2 {{ font-size: 1.35rem !important; }}
  h3 {{ font-size: 1.1rem !important; }}

  [data-testid="stForm"] {{
    padding: 1rem 1.1rem !important;
    border-radius: 16px !important;
  }}
  [data-testid="stMetric"] {{ padding: 10px 12px; }}

  /* Objetivos comodos para el dedo */
  .stButton > button,
  .stDownloadButton > button,
  [data-testid="stFormSubmitButton"] > button {{
    width: 100%;
    min-height: 44px;
  }}
  section[data-testid="stSidebar"] label[data-testid="stRadioOption"] {{
    padding: 12px 14px;
  }}

  /* Las pestanas del resultado del triaje se desplazan en horizontal */
  [data-testid="stTabs"] [data-baseweb="tab-list"] {{
    overflow-x: auto;
    scrollbar-width: none;
  }}
  [data-testid="stTabs"] [data-baseweb="tab-list"]::-webkit-scrollbar {{ display: none; }}
}}

/* --- Varios ----------------------------------------------------------- */
hr, [data-testid="stDivider"] {{ border-color: var(--tapia-borde) !important; }}
code, pre, [data-testid="stCode"] {{ border-radius: 12px !important; }}
[data-testid="stCaptionContainer"] p {{ color: var(--tapia-texto-suave) !important; }}
</style>
"""


def inject() -> None:
    """Aplica el tema. Se llama una vez, justo despues de set_page_config."""
    st.markdown(_css(), unsafe_allow_html=True)


def urgency_badge_html(label: str, bucket: str) -> str:
    """Pastilla de prioridad con el color correspondiente al bucket."""
    color = URGENCIA.get(bucket, TEXTO_SUAVE)
    return (
        f'<div style="background:{color};color:#fff;padding:16px 22px;'
        f'border-radius:16px;font-size:1.15rem;font-weight:600;'
        f'letter-spacing:-.01em;text-align:center;margin:12px 0;">{label}</div>'
    )
