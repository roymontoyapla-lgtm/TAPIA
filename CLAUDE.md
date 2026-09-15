# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

TAPIA es una aplicación Streamlit de triaje clínico orientativo: cruza un cuestionario,
datos de wearable, analíticas y antropometría para priorizar la cita y generar informes
y planes de alimentación y ejercicio.

## La raíz del repositorio ES el paquete `tapia`

No existe ninguna carpeta `tapia/`. Todo el código importa con `tapia.core...`,
`tapia.ui...`, etc., y el directorio raíz se registra bajo ese nombre en tiempo de
ejecución (`importlib.util.spec_from_file_location`) desde tres sitios:

- `conftest.py` — para que `pytest` funcione desde la raíz
- `streamlit_app.py` y `main.py` — al arrancar cada entrada
- `pyproject.toml` lo mapea con `package-dir = {"tapia" = "."}`

Esto existe porque el directorio clonado puede llamarse `TAPIA`, `tapia-main` o
cualquier cosa. **No sustituyas esos bloques por manipulaciones de `sys.path` que
dependan del nombre de la carpeta**, y usa siempre imports relativos (`from ...core.x`)
dentro de los módulos.

Hubo una copia duplicada del paquete en `tapia/` que se borró en `2b86d03`; si
reaparece, es un error.

## Comandos

```bash
python -m pytest                          # suite completa, desde la raíz del repo
python -m pytest tests/test_triage.py      # un fichero
python -m pytest tests/test_lifestyle.py::TestEnergy::test_bmr_hombre_mifflin   # un test
python -m pytest -k "dropbox"              # por nombre

streamlit run streamlit_app.py             # la aplicación (entrada real)
pip install -r requirements.txt
```

`pyproject.toml` fija `testpaths = ["tests"]` y `addopts = "-v --tb=short"`.

`main.py` arranca una UI de escritorio en Tkinter (`ui/app.py`) que quedó **obsoleta**:
no tiene antropometría, analíticas, planes ni multiusuario. Todo el desarrollo va a la
versión Streamlit.

## Arquitectura

### Flujo del triaje (`ui/streamlit_pages/page_triage.py`)

Es el orquestador principal; para entenderlo hay que leerlo junto a `core/triage.py`:

1. Formulario → `PatientInfo` y `Questionnaire` (`core/models.py`).
2. Wearable → `wearables/detector.py` normaliza a dicts de TAPIA →
   `db.import_wearable_records()` (incremental) → `core/wearable.py` `filter_by_days` +
   `summarize` producen `WearableSummary` a 30 y 56 días.
3. Puntuación: `triage_ap_vs_specialist()` (AP vs especialista) y
   `urgency_score_and_bucket()` (score local) → bucket de `urgente` / `7_dias` / `2_semanas`.
4. Sumandos opcionales: `core/lab_analyzer.lab_urgency_score()` y
   `core/anthropometry.obesity_urgency_score()` añaden puntos y motivos.
5. IA: `ai/gpt_client.get_ai_urgency()` recibe un informe preliminar y devuelve su bucket.
6. `merge_buckets()` se queda siempre con **el más urgente** de local e IA; después el
   score combinado puede escalar aún más la prioridad. La estrategia es deliberadamente
   conservadora: no la relajes sin pedirlo.
7. `core/report.build_report()` arma el informe de texto, que se guarda cifrado y se
   exporta a PDF.

### Umbrales clínicos en `config.yaml`

Los valores clínicos (horas de sueño, pasos, FC en reposo, pesos del score, objetivos
OMS del plan, modelo de IA) viven en `config.yaml` y se leen por `core/config.py`, que
expone un único objeto `cfg`. Al añadir un umbral: entrada en `config.yaml` + clase
`_Algo` con `_deep_get(..., default=...)` + atributo en `Config`. **No claves mágicas
repartidas por el código.**

### Adaptadores de wearable

`wearables/base.py` define `NormalizedRecord` y el contrato `can_handle()` / `normalize()`.
`wearables/detector.py` prueba los adaptadores **en orden, del más específico al más
genérico**, con `TapiaAdapter` de último recurso. Al añadir uno:

- Colócalo antes de los genéricos y comprueba en los tests que **no secuestra** formatos
  ya soportados (ver `TestAppleAutoExportAdapter::test_no_secuestra_otros_formatos` en
  `tests/test_wearable_cloud.py`).
- `AppleHealthXMLAdapter` es el único que recibe `bytes` (XML o ZIP) y acepta `days=`.
- `adapter_apple_auto.py` (Health Auto Export) agrega varios puntos por día: **suma**
  pasos, ejercicio y sueño; **promedia** FC, HRV y respiraciones.

### Carga desde la nube

`wearables/cloud.py` (Dropbox sobre `requests`, sin SDK) + `wearables/sync.py`
orquestan la carga bajo demanda; el estado vive en `wearable_sync_state` para no
redescargar. Apple Health no tiene API: los JSON los deja una app del móvil en Dropbox.
Credenciales por `.env` (ver `.env.example`); `scripts/dropbox_setup.py` hace el flujo
OAuth y las escribe.

### Persistencia y cifrado

Todo pasa por `db/database.py` (SQLite, `init_db()` idempotente). `db/crypto.py` cifra
con Fernet usando la clave de `.tapia_key` (se genera sola, está en `.gitignore`).

- Van **cifrados**: nombres de paciente, texto de informes y de planes.
- `_safe_decrypt()` tolera filas antiguas en claro; úsalo al leer campos cifrados.
- `import_wearable_records()` y `save_anthropometry()` son idempotentes por
  `(patient_id, fecha)`: se pueden reejecutar sin duplicar.
- Al añadir una tabla por paciente, acuérdate de borrarla en `delete_patient_data()`
  (RGPD) y de cubrirlo con un test.

### IA: cuatro puntos de entrada, todos degradables

`ai/gpt_client.py` (urgencia), `core/lab_analyzer.py` (Claude Vision sobre fotos de
analíticas), `core/patient_report.py` (informe integral) y `ai/lifestyle_client.py`
(redacción del plan). Reglas que comparten:

- Sin clave, sin librería o con `provider` desactivado **devuelven un fallback y la app
  sigue funcionando**. Mantén ese contrato.
- Anonimizan el nombre del paciente antes de enviar cuando `ai.anonymize_before_send`.
- El cálculo numérico nunca lo hace la IA: `core/lifestyle.py` calcula el plan de forma
  determinista y la IA solo lo redacta.

### Páginas, permisos y auditoría

`streamlit_app.py` registra cada página en `all_pages` como
`"Etiqueta": (función_run, "permiso")`, y el permiso tiene que existir en `PERMISSIONS`
de `auth/auth.py` (roles: admin, medico, consultor). Cada página vuelve a comprobar el
permiso con `has_permission()`. Las acciones sensibles se registran con
`compliance/audit.py` (`log(Action.X, ...)`); `compliance/gdpr.py` cubre consentimiento,
exportación y borrado.

## Convenciones

- **Sin acentos en el código nuevo** (comentarios, docstrings y textos de interfaz):
  el código reciente es ASCII puro. `config.yaml` sí los usa en sus comentarios.
- Todo el contenido de cara al usuario está en español.
- Mensajes de commit: `vNN - descripcion corta` para funcionalidad; `fix - ...` o
  `limpieza - ...` para el resto.
- Los informes y planes terminan siempre con el aviso de que no sustituyen la
  valoración clínica.

## Limitaciones conocidas

- **SQLite efímero en Streamlit Cloud**: el disco se reinicia en cada despliegue, así
  que lo guardado se pierde y la base vuelve a la copia del repositorio. Es el principal
  freno para cualquier automatización.
- `tapia_history.db` está versionado en git pese a figurar en `.gitignore` (se subió
  antes de ignorarlo). No lo incluyas en commits: si aparece modificado tras ejecutar
  tests o la app, restáuralo con `git checkout -- tapia_history.db`.
