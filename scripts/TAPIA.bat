@echo off
rem ---------------------------------------------------------------
rem  TAPIA - lanzador para Windows
rem  Arranca el servidor y abre la aplicacion en el navegador.
rem  Cierra esta ventana para detener TAPIA.
rem ---------------------------------------------------------------

cd /d "%~dp0.."
title TAPIA

where python >/dev/null 2>nul
if errorlevel 1 (
    echo.
    echo No se encuentra Python en este equipo.
    echo Instalalo desde python.org y marca "Add Python to PATH".
    echo.
    pause
    exit /b 1
)

python -c "import streamlit" >/dev/null 2>nul
if errorlevel 1 (
    echo.
    echo Faltan las dependencias. Instalalas con:
    echo     python -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

echo.
echo   TAPIA se esta iniciando...
echo   El navegador se abrira solo en unos segundos.
echo.
echo   NO CIERRES ESTA VENTANA mientras uses la aplicacion.
echo.

rem --server.headless=false hace que Streamlit abra el navegador
rem (config.yaml del proyecto lo deja en true para el despliegue)
python -m streamlit run streamlit_app.py --server.headless=false

if errorlevel 1 (
    echo.
    echo TAPIA se ha detenido con un error.
    pause
)
