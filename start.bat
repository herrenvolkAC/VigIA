@echo off
chcp 65001 >nul
cd /d %~dp0

echo.
echo  ===========================================
echo   VigIA v2.0  ^|  Gemelo Operativo WMS
echo   CD Coto
echo  ===========================================
echo.

REM Usar siempre un entorno virtual local a la carpeta de VigIA.
REM Esto evita depender de las librerias instaladas en cada usuario de Windows.
set "VENV_DIR=%~dp0venv"
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"

if not exist "%PYTHON_EXE%" (
    echo  Preparando entorno local de VigIA...
    python --version >nul 2>&1
    if not errorlevel 1 (
        python -m venv "%VENV_DIR%"
    ) else (
        py -3 --version >nul 2>&1
        if errorlevel 1 (
            echo  [ERROR] Python no encontrado en PATH.
            echo  Instala Python 3.10+ desde https://python.org
            pause
            exit /b 1
        )
        py -3 -m venv "%VENV_DIR%"
    )
    if errorlevel 1 (
        echo  [ERROR] No se pudo crear el entorno virtual local.
        pause
        exit /b 1
    )
)

"%PYTHON_EXE%" --version >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] El entorno local de VigIA no se pudo iniciar.
    echo  Revisa permisos sobre la carpeta: %VENV_DIR%
    pause
    exit /b 1
)

"%PYTHON_EXE%" -m pip --version >nul 2>&1
if errorlevel 1 (
    "%PYTHON_EXE%" -m ensurepip --upgrade
)

REM Instalar dependencias si faltan
echo  Verificando dependencias...
"%PYTHON_EXE%" -c "import aiosqlite, fastapi, openpyxl, oracledb, uvicorn, xlrd, multipart" >nul 2>&1
if errorlevel 1 (
    echo  Instalando dependencias en entorno local de VigIA...
    if exist offline_packages (
        echo  Usando paquetes locales de offline_packages...
        "%PYTHON_EXE%" -m pip install --no-index --find-links offline_packages -r requirements.txt
    ) else (
        "%PYTHON_EXE%" -m pip install -r requirements.txt
    )
    if errorlevel 1 (
        echo  [ERROR] No se pudieron instalar las dependencias.
        pause
        exit /b 1
    )
    echo  Dependencias instaladas correctamente.
    echo.
)

"%PYTHON_EXE%" -c "import fastapi, uvicorn" >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] El entorno local no tiene FastAPI/Uvicorn instalados.
    echo  Revisa la instalacion de dependencias o la carpeta offline_packages.
    pause
    exit /b 1
)

REM Verificar que existe .env
if not exist .env (
    echo  [ADVERTENCIA] No se encontro el archivo .env
    echo  Copiando .env.example como .env ...
    copy .env.example .env
    echo.
    echo  Edita el archivo .env con tus credenciales
    echo  y vuelve a ejecutar start.bat
    echo.
    pause
    exit /b 1
)

echo  Iniciando servidor...
echo  Acceso local:  http://localhost:9999
echo  Acceso red:    http://TU-IP-LOCAL:9999
echo.
echo  Presiona Ctrl+C para detener el servidor.
echo.
"%PYTHON_EXE%" main.py
pause
