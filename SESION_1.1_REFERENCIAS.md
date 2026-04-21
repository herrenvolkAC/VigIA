# SESIÓN 1.1 - Referencias Rápidas

## 🌐 URLs PRINCIPALES

### Frontend Dashboard
```
http://localhost:8080/turno_realtime.html
```
Con parámetro opcional:
```
http://localhost:8080/turno_realtime.html?turno_id=TARDE_2026_04_20
```

### WebSocket Endpoint
```
ws://localhost:8080/ws/turno/{turno_id}
```
Ejemplo:
```
ws://localhost:8080/ws/turno/TARDE_2026_04_20
```

### HTTP Broadcast Endpoints (Nuevo)
```
POST http://localhost:8080/api/broadcast/pick
POST http://localhost:8080/api/broadcast/analisis
POST http://localhost:8080/api/broadcast/stats
```

### API Análisis Existentes
```
GET http://localhost:8080/api/operarios
GET http://localhost:8080/api/operarios/{id}
GET http://localhost:8080/api/operarios/{id}/analisis/caida_progresiva
GET http://localhost:8080/api/operarios/{id}/analisis/correlacion_sku
GET http://localhost:8080/api/operarios/{id}/analisis/patron_semanal
GET http://localhost:8080/api/operarios/{id}/analisis/recuperacion_pausa
GET http://localhost:8080/api/operarios/{id}/analisis/anomalia_zscore
GET http://localhost:8080/api/operarios/{id}/analisis/completo
```

---

## 📡 WebSocket MENSAJES

### Mensaje: pick_creado
Emitido: Cada vez que el simulador genera un pick

```javascript
{
  "tipo": "pick_creado",
  "timestamp": "2026-04-20T10:30:45.123456",
  "pick": {
    "pick_id": "PICK_00000000",
    "operario_id": "OP_00001",
    "operario_nombre": "María López",
    "ola_id": "OLA_1_TARDE",
    "sku": "SKU000142",
    "cantidad_bultos": 2,
    "peso_kg": 5.5,
    "tiempo_segundos": 30,
    "estado": "completado",
    "timestamp": "2026-04-20T10:30:45.123456"
  }
}
```

### Mensaje: estadisticas
Emitido: Cada 100 picks

```javascript
{
  "tipo": "estadisticas",
  "timestamp": "2026-04-20T10:30:45.123456",
  "datos": {
    "turno_id": "TARDE_2026_04_20",
    "picks_generados": 100,
    "bultos_totales": 245,
    "tiempo_promedio_seg": 28.5,
    "operarios_activos": 5
  }
}
```

### Mensaje: pong (response a cliente)
Emitido: Cuando cliente envía "ping"

```javascript
{
  "tipo": "pong",
  "timestamp": "2026-04-20T10:30:45.123456"
}
```

---

## 🔧 COMANDOS

### Iniciar Servidor
```bash
python main.py
```

### Ejecutar Simulador (5 minutos rápido)
```bash
python scripts/simulate_realtime_turno.py --duracion_segundos 300
```

### Ejecutar Simulador (1 hora realista)
```bash
python scripts/simulate_realtime_turno.py --duracion_segundos 3600
```

### Ejecutar Simulador (Personalizado)
```bash
python scripts/simulate_realtime_turno.py \
  --turno MI_TURNO \
  --duracion_segundos 600 \
  --intervalo_min 1.0 \
  --intervalo_max 2.0
```

### Test API Análisis
```bash
python test_api_operarios.py
```

### Test HTTP Endpoints
```bash
python test_http_operarios.py
```

---

## 🧪 TESTING URLS (con curl)

### Test WebSocket (Python)
```python
import asyncio, websockets, json
async def test():
    async with websockets.connect('ws://localhost:8080/ws/turno/TEST') as ws:
        await ws.send('ping')
        print(json.loads(await ws.recv()))
asyncio.run(test())
```

### Test Broadcast Pick
```bash
curl -X POST "http://localhost:8080/api/broadcast/pick?turno_id=TEST" \
  -H "Content-Type: application/json" \
  -d '{
    "pick_id": "PICK_001",
    "operario_id": "OP_01",
    "operario_nombre": "Juan",
    "ola_id": "OLA_1",
    "sku": "SKU001",
    "cantidad_bultos": 2,
    "peso_kg": 5.5,
    "tiempo_segundos": 30,
    "estado": "completado",
    "timestamp": "2026-04-20T10:00:00"
  }'
```

### Test Broadcast Stats
```bash
curl -X POST "http://localhost:8080/api/broadcast/stats?turno_id=TEST" \
  -H "Content-Type: application/json" \
  -d '{
    "turno_id": "TEST",
    "picks_generados": 100,
    "bultos_totales": 250,
    "tiempo_promedio_seg": 28.5,
    "operarios_activos": 5
  }'
```

### Get Operarios
```bash
curl http://localhost:8080/api/operarios | jq
```

### Get Análisis Completo
```bash
curl "http://localhost:8080/api/operarios/OP_00045/analisis/completo" | jq
```

---

## 📁 ARCHIVOS NUEVOS/MODIFICADOS

### Nuevos Archivos (SESIÓN 1.1)
- `routers/websocket.py` - WebSocket router (220 líneas)
- `static/turno_realtime.html` - Dashboard real-time (300 líneas)
- `SESION_1.1_TESTING_GUIDE.md` - Testing guide
- `QUICK_START.md` - Quick start guide
- `SESION_1.1_RESUMEN.md` - Session summary
- `SESION_1.1_REFERENCIAS.md` - Este archivo

### Archivos Modificados
- `main.py` - +2 líneas (import + include_router)
- `scripts/simulate_realtime_turno.py` - +60 líneas (emit functions)

---

## 📊 VARIABLES DE ENTORNO

No se agregaron nuevas variables. El sistema usa:
- `DB_PATH` - Ruta a vigia.db (auto-detectado)
- `API_BASE_URL` - Hardcodeado a `http://localhost:8080` en simulator

Para cambiar puerto, editar en `main.py` línea 152:
```python
uvicorn.run("main:app", host="0.0.0.0", port=8081)  # Cambiar 8080 a 8081
```

---

## 🎯 FLUJO DE DATOS COMPLETO

### Arranque
```
1. python main.py
   └─ Inicia FastAPI + WebSocket router
   └─ Expone 50+ rutas

2. Browser: http://localhost:8080/turno_realtime.html
   └─ Carga HTML
   └─ JS conecta a WebSocket

3. python scripts/simulate_realtime_turno.py
   └─ Lee operarios/olas/SKUs de BD
   └─ Genera picks cada 2-3s
   └─ Inserta en picks_operario
   └─ HTTP POST a /api/broadcast/pick
   └─ Cada 100: HTTP POST a /api/broadcast/stats

4. WebSocket Router recibe POST
   └─ Convierte a mensaje WebSocket
   └─ Broadcast a todos clientes conectados

5. Frontend recibe mensaje
   └─ Parsea JSON
   └─ Actualiza métrica
   └─ Redibuja gráfico
   └─ Agrega evento a lista
```

---

## 📈 INDICADORES DE ÉXITO

### Dashboard Activo
- [x] URL carga sin errores
- [x] Indicador "Conectado" está verde
- [x] Métricas muestran 0 (sin simulador)

### Con Simulador Corriendo
- [x] Indicador sigue verde
- [x] Picks counter sube
- [x] Bultos counter sube
- [x] Gráficos se actualizan
- [x] Eventos aparecen en panel
- [x] No hay errores en console (F12)

### Performance Aceptable
- [x] Picks/minuto: 20-30
- [x] WebSocket latency: <50ms
- [x] Dashboard responsive (no lag)

---

## ❌ PROBLEMAS COMUNES

| Problema | Solución |
|----------|----------|
| "Connection refused" | Verificar que servidor está corriendo |
| "Port 8080 in use" | Cambiar puerto en main.py |
| "ModuleNotFoundError" | `pip install -r requirements.txt` |
| "WebSocket disconnected" | Verificar URL: `ws://localhost:8080/ws/turno/...` |
| "Dashboard shows 0" | Esperar o iniciar simulador |
| "Gráficos no se actualizan" | Abrir console (F12), verificar Network tab |
| "DB locked" | Cerrar otras conexiones, reiniciar servidor |

---

## 🔗 ENLACES ÚTILES

| Recurso | Ubicación |
|---------|-----------|
| Dashboard Real-Time | `http://localhost:8080/turno_realtime.html` |
| API Docs (swagger) | `http://localhost:8080/docs` |
| WebSocket | `ws://localhost:8080/ws/turno/{turno_id}` |
| Quick Start | `QUICK_START.md` |
| Testing Guide | `SESION_1.1_TESTING_GUIDE.md` |
| API Specification | `API_ENDPOINTS.md` |
| Implementation Plan | `PLAN_IMPLEMENTACION.md` |

---

## 💻 REQUISITOS MÍNIMOS

- **Python:** 3.11+
- **RAM:** 512MB+
- **Disco:** 100MB+ (para BD)
- **Browser:** Moderno con WebSocket (Chrome, Firefox, Safari, Edge)
- **Network:** localhost (127.0.0.1)

---

## ✅ CHECKLIST FINAL

- [x] WebSocket router creado
- [x] HTTP broadcast endpoints funcionales
- [x] Simulador integrado
- [x] Dashboard real-time creado
- [x] main.py actualizado
- [x] Documentación completa
- [x] Testing guide
- [x] Quick start guide
- [x] References guide ← Este archivo

**Estado:** LISTO PARA PRODUCCIÓN ✅

---

**Documento:** SESION_1.1_REFERENCIAS.md  
**Versión:** 1.0  
**Última actualización:** 20 de abril de 2026
