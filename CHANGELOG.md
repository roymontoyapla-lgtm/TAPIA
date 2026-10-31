# Changelog de TAPIA

## v1.1.1 - 2026-10-31 (seguridad)

### Seguridad
- **Admin inicial sin clave por defecto.** El usuario `admin` solo se crea si no
  hay usuarios y existe la variable `TAPIA_ADMIN_PASSWORD` (minimo 12 caracteres),
  definida en `.env` o en los Secrets de Streamlit Cloud.
- **Clave antigua bloqueada.** La clave por defecto publicada en versiones
  anteriores ya no da acceso a ningun usuario; si el `admin` aun la tuviera, se
  sustituye por `TAPIA_ADMIN_PASSWORD`.
- **Ninguna clave en el log** ni en la pantalla de login.
- **Contrasenas con PBKDF2-HMAC-SHA256** (600 000 iteraciones) en lugar de
  SHA-256 de una vuelta. Los hashes antiguos se migran solos en el siguiente
  login correcto; nadie tiene que cambiar su clave.
- Comparacion de hashes en tiempo constante y mismo coste de login para usuarios
  inexistentes.

### Otros
- `.env.example` documenta `TAPIA_ADMIN_PASSWORD`.
- Nuevos tests en `tests/test_auth.py` (13), con datos sinteticos.

### Pendiente conocido
- `tapia_history.db` sigue versionada en el repositorio y se reinicia en cada
  despliegue de Streamlit Cloud.
- 5 tests de Dropbox (`tests/test_wearable_cloud.py`) fallan en local, ya
  fallaban antes de esta version.
