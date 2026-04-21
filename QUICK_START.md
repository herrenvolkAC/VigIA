# VigIA 3.0 - QUICK START GUIDE

**Status:** SESIÓN 1.1 COMPLETADA ✅  
**Componentes:** Backend API + WebSocket + Real-Time Simulator + Dashboard

---

## 🚀 INICIAR EN 2 MINUTOS

### Requisitos
- Python 3.11+
- Dependencias: `pip install -r requirements.txt`
- Base de datos: `vigia.db` (creada automáticamente)

### Pasos:

**1. Terminal 1 - Iniciar Servidor:**
```bash
cd C:\Ingenieria\VigIA
python main.py
```
Esperado: Verás "Uvicorn running on http://0.0.0.0:8080"

**2. Abre en Browser:**
```
http://localhost:8080/turno_realtime.html
```

**3. Terminal 2 - Ejecutar Simulador:**
```bash
python scripts/simulate_realtime_turno.py --duracion_segundos 300
```

**4. Observa el Dashboard:**
- Indicador de conexión se pone verde
- Métricas comienzan a subir
- Gráficos se actualizan en tiempo real
- Panel de eventos muestra cada pick

---

## 📡 COMPONENTES PRINCIPALES

### 1. API REST (Análisis Inteligente)
**URL:** `http://localhost:8080/api/operarios`

```bash
# Ver todos los operarios
curl http://localhost:8080/api/operarios

# Análisis completo de operario
curl "http://localhost:8080/api/operarios/OP_00045/analisis/completo"

# Análisis específicos:
# - /api/operarios/{id}/analisis/caida_progresiva
# - /api/operarios/{id}/analisis/correlacion_sku
# - /api/operarios/{id}/analisis/patron_semanal
# - /api/operarios/{id}/analisis/recuperacion_pausa
# - /api/operarios/{id}/analisis/anomalia_zscore
```

### 2. WebSocket Real-Time
**URL:** `ws://localhost:8080/ws/turno/{turno_id}`

Mensajes emitidos:
- `pick_creado` - Nuevo pick generado
- `estadisticas` - Stats cada 100 picks
- `analisis_actualizado` - Análisis completado

### 3. Dashboard Real-Time
**Ubicación:** `http://localhost:8080/turno_realtime.html`

Muestra:
- ✅ Picks en tiempo real
- ✅ Bultos acumulados
- ✅ Operarios activos
- ✅ Gráficos actualizados
- ✅ Panel de eventos

### 4. Simulador Turno
**Comando:** `python scripts/simulate_realtime_turno.py`

Opciones:
```bash
--turno TURNO_ID                  # ID del turno (default: auto)
--duracion_segundos N             # Duración en segundos (default: 3600)
--intervalo_min 2.0               # Min entre picks (default: 2.0)
--intervalo_max 3.5               # Max entre picks (default: 3.5)
```

Ejemplos:
```bash
# 5 minutos rápido
python scripts/simulate_realtime_turno.py --duracion_segundos 300

# 1 hora realista
python scripts/simulate_realtime_turno.py --duracion_segundos 3600

# Turno personalizado
python scripts/simulate_realtime_turno.py --turno MI_TURNO --duracion_segundos 1800
```

---

## 📊 BASE DE DATOS

### Tablas Principales
- `picks_operario` - 510k+ picks históricos
- `operarios` - 10 operarios
- `articulos_maestro` - 2,000 SKUs
- `pausas_operario` - Descansos (2,766)
- `errores_operario` - Errores (3,732)
- `ausentismo_operario` - Ausencias

### Consultas Útiles
```bash
# Contar picks
sqlite3 vigia.db "SELECT COUNT(*) FROM picks_operario;"

# Ver última hora
sqlite3 vigia.db "SELECT * FROM picks_operario ORDER BY timestamp DESC LIMIT 10;"

# Velocidad promedio por operario
sqlite3 vigia.db "SELECT operario_id, AVG(tiempo_segundos) FROM picks_operario GROUP BY operario_id;"
```

---

## 🧪 TESTING

### Test Rápido (1 minuto)
```bash
python test_api_operarios.py
```
Esperado: `5/5 tests PASADOS [SUCCESS]`

### Test HTTP (con servidor corriendo)
```bash
python test_http_operarios.py
```

### Test WebSocket Manual
```bash
python -c "
import asyncio, websockets, json
async def test():
    async with websockets.connect('ws://localhost:8080/ws/turno/TEST') as ws:
        await ws.send('ping')
        print(json.loads(await ws.recv()))
asyncio.run(test())
"
```

---

## 📁 ESTRUCTURA DE ARCHIVOS

```
VigIA/
├── main.py                          ← Servidor FastAPI
├── routers/
│   ├── analisis_inteligente.py     ← 5 análisis IA
│   ├── operarios.py                ← 7 endpoints
│   └── websocket.py                ← WebSocket router
├── scripts/
│   ├── simulate_realtime_turno.py  ← Simulador
│   └── generate_historical_data.py
├── static/
│   ├── turno_realtime.html         ← Dashboard NUEVO
│   └── picking.html                ← UI principal
├── vigia.db                         ← SQLite DB
├── requirements.txt
├── README_SESION_1.md
├── SESION_1.1_TESTING_GUIDE.md
└── QUICK_START.md (este archivo)
```

---

## ⚡ COMMANDOS RÁPIDOS

| Tarea | Comando |
|-------|---------|
| Iniciar servidor | `python main.py` |
| Tests inteligencia | `python test_api_operarios.py` |
| Ver operarios | `curl http://localhost:8080/api/operarios` |
| Simular turno | `python scripts/simulate_realtime_turno.py` |
| Ver dashboard | Browser: `http://localhost:8080/turno_realtime.html` |
| Consultar BD | `sqlite3 vigia.db "SELECT COUNT(*) FROM picks_operario;"` |

---

## 🔧 TROUBLESHOOTING

**"Port already in use"**
```bash
# Cambiar puerto en main.py línea 152:
# uvicorn.run("main:app", host="0.0.0.0", port=8081)  # Cambiar 8080 a 8081
```

**"ModuleNotFoundError: No module named 'fastapi'"**
```bash
pip install -r requirements.txt
```

**"WebSocket connection failed"**
1. Verifica que el servidor está corriendo
2. Verifica la URL: `ws://localhost:8080/ws/turno/...`
3. Abre browser console (F12) para ver errores

**"Database locked"**
- Cierra todas las conexiones a vigia.db
- Reinicia el servidor

---

## 📈 MÉTRICAS DE DESEMPEÑO

**Esperados:**
- Picks/minuto: 20-30
- Response time: <100ms
- WebSocket latency: <50ms
- DB query time: <100ms
- Dashboard update: 100-500ms

---

## 🎓 ANÁLISIS INTELIGENTES

### 1. Caída Progresiva (Fatiga)
```bash
curl "http://localhost:8080/api/operarios/OP_00045/analisis/caida_progresiva"
```
Detecta si el operario se cansa durante la ola

### 2. Correlación SKU
```bash
curl "http://localhost:8080/api/operarios/OP_00045/analisis/correlacion_sku"
```
Identifica SKUs en los que es experto

### 3. Patrón Semanal
```bash
curl "http://localhost:8080/api/operarios/OP_00045/analisis/patron_semanal"
```
Muestra variación productividad por día

### 4. Recuperación Pausa
```bash
curl "http://localhost:8080/api/operarios/OP_00045/analisis/recuperacion_pausa"
```
Mide mejora después de descanso

### 5. Anomalía Z-Score
```bash
curl "http://localhost:8080/api/operarios/OP_00045/analisis/anomalia_zscore"
```
Detecta picks anormales estadísticamente

---

## 📞 RECURSOS

- **Documentación Completa:** `README_SESION_1.md`
- **Testing Guide:** `SESION_1.1_TESTING_GUIDE.md`
- **Plan Implementación:** `PLAN_IMPLEMENTACION.md`
- **Especificación API:** `API_ENDPOINTS.md`
- **Estado Proyecto:** `STATUS.md`

---

## ✅ CHECKLIST PARA DEMO

- [ ] Servidor inicia sin errores
- [ ] Dashboard carga y conecta
- [ ] Simulador genera picks
- [ ] Métricas se actualizan
- [ ] Gráficos muestran datos
- [ ] Panel de eventos funciona
- [ ] WebSocket no desconecta
- [ ] Performance es aceptable

---

**Últimas actualizaciones:** 20 de abril de 2026  
**Versión:** 3.0.0 - SESIÓN 1.1 COMPLETADA ✅
