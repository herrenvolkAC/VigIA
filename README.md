# VigIA v2.0 · Gemelo Operativo WMS — CD Coto

Sistema de monitoreo de operaciones de picking en tiempo real con análisis por IA.
Soporta **Claude (Anthropic)** y **Azure OpenAI** como proveedores de IA intercambiables.

## MÃ³dulo: Sugerencias Plantel Operativo

Dentro de `picking.html` ahora existe el tab **Sugerencias Plantel Operativo**.

El flujo permite:
- seleccionar turno,
- cargar bultos por `SECTOR SECOS` y `VARIOS NO ALIMENTOS`,
- calcular una sugerencia de asignaciÃ³n de plantel contra baseline,
- proyectar capacidad grupal y hora estimada de fin,
- guardar escenarios `What If`.

Fuente de datos:
- prioriza histÃ³rico Oracle con mapping de almacÃ©n desde `VW_UBICACIONES_DIVISION`,
- si Oracle no estÃ¡ disponible, usa fallback local sobre `vigia.db`.

---

## Requisitos

- Python 3.10 o superior
- Windows 10/11 (o cualquier OS con Python)

---

## Instalación y primer arranque

```bash
# 1. Instalar dependencias
pip install -r requirements.txt

# 2. Configurar credenciales
copy .env.example .env
# Editá .env con tu API key de Anthropic o Azure

# 3. Arrancar el servidor
python main.py
# — o en Windows, doble clic en start.bat —

# 4. Abrir en el navegador
#    Misma PC:      http://localhost:8080
#    Red local:     http://192.168.X.X:8080
```

---

## Estructura del proyecto

```
vigia/
├── main.py                  ← Servidor FastAPI principal
├── .env                     ← Credenciales (NO subir a git)
├── .env.example             ← Template de configuración
├── requirements.txt
├── start.bat                ← Arranque automático Windows
├── vigia.db                 ← SQLite (se crea automáticamente)
├── db/
│   └── schema.py            ← 4 tablas: turnos, movimientos, predicciones, modelos
├── routers/
│   ├── ai.py                ← /api/analyze · /api/chat · /api/providers
│   └── data.py              ← /api/snapshot · /api/turno/activo
└── static/
    └── index.html           ← Frontend completo (single-file)
```

---

## Configuración de proveedores (.env)

```env
# Proveedor activo: "claude" | "azure"
AI_PROVIDER=claude

# Claude (Anthropic)
ANTHROPIC_API_KEY=sk-ant-api03-...

# Azure OpenAI (opcional)
AZURE_OPENAI_ENDPOINT=https://mi-empresa.openai.azure.com/
AZURE_OPENAI_API_KEY=abc123...
AZURE_OPENAI_DEPLOYMENT=gpt-4o-coto
AZURE_OPENAI_API_VERSION=2024-02-01
```

El proveedor activo se puede cambiar desde la interfaz sin reiniciar el servidor.

---

## Endpoints de la API

| Método | Endpoint             | Descripción                                    |
|--------|----------------------|------------------------------------------------|
| GET    | `/`                  | Frontend principal                             |
| GET    | `/api/providers`     | Lista proveedores disponibles y cuál está activo |
| POST   | `/api/analyze`       | Análisis IA del estado operativo → alertas     |
| POST   | `/api/chat`          | Chat con el asistente operativo                |
| POST   | `/api/snapshot`      | Guarda datos del xlsx en la BD                 |
| GET    | `/api/turno/activo`  | Devuelve el turno abierto actual               |
| GET    | `/api/turnos`        | Lista los últimos turnos                       |

Documentación interactiva disponible en: `http://localhost:8080/docs`

---

## Uso con planilla real

1. Abrí la app en el navegador
2. Hacé clic en **"Cargar DatosModelo.xlsx"**
3. La app pasa automáticamente a **modo PLANILLA REAL**
4. Los datos se guardan en `vigia.db` automáticamente
5. El análisis IA se actualiza cada 30 segundos

## Uso en modo simulación

Sin necesidad de planilla. Elegí un escenario (Normal / Ritmo lento / Pico / Cuello de botella)
y el sistema simula el avance del turno con datos generados.

---

## Seguridad

- Las API keys **nunca** se exponen al frontend ni aparecen en logs
- El archivo `.env` está excluido del control de versiones
- Si ningún proveedor está configurado, el sistema funciona con alertas locales como fallback

---

## Acceso desde la red local

El servidor escucha en `0.0.0.0:8080`, por lo que cualquier dispositivo en la misma red puede acceder usando la IP local de la PC donde corre el servidor:

```
http://192.168.1.XX:8080
```

Para encontrar tu IP local en Windows: `ipconfig` → "Dirección IPv4"
