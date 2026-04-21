@echo off
chcp 65001 >nul
cd /d %~dp0

echo.
echo  ===========================================
echo   VigIA v2.0  ^|  Gemelo Operativo WMS
echo   CD Coto
echo  ===========================================
echo.

REM Verificar Python
python --version >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Python no encontrado en PATH.
    echo  Instala Python 3.10+ desde https://python.org
    pause
    exit /b 1
)

REM Instalar dependencias si faltan
echo  Verificando dependencias...
python -c "import uvicorn" >nul 2>&1
if errorlevel 1 (
    echo  Instalando dependencias ^(primera vez^)...
    pip install -r requirements.txt
    if errorlevel 1 (
        echo  [ERROR] No se pudieron instalar las dependencias.
        pause
        exit /b 1
    )
    echo  Dependencias instaladas correctamente.
    echo.
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
python main.py
pause
