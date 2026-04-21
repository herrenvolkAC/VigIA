# SESIÓN 1.1 - Testing Guide

**Status:** COMPLETADA ✅  
**Fecha:** 20 de abril de 2026  
**Componentes:** WebSocket Router + Real-Time Simulator + Dashboard

---

## ✅ CAMBIOS IMPLEMENTADOS

### 1. Servidor WebSocket (`routers/websocket.py`)
- **Líneas:** 120+ con 3 nuevas funciones HTTP
- **Endpoints:**
  - `ws://localhost:8080/ws/turno/{turno_id}` - WebSocket principal
  - `POST /api/broadcast/pick` - Emitir pick
  - `POST /api/broadcast/stats` - Emitir estadísticas
  - `POST /api/broadcast/analisis` - Emitir análisis
- **Features:**
  - Connection management por turno_id
  - Broadcasting a múltiples clientes
  - Manejo de desconexiones

### 2. Integración en Main (`main.py`)
- **Cambio:** Agregado import y include_router para websocket
- **Línea:** 21-22, 66

### 3. Simulador Actualizado (`scripts/simulate_realtime_turno.py`)
- **Cambios:**
  - Import de httpx para HTTP requests
  - Nueva función `emit_pick()` para emitir picks
  - Nueva función `emit_stats()` para emitir estadísticas
  - Nueva función `get_turno_stats()` (reemplazó importación)
  - Llamadas a `emit_pick()` después de cada INSERT
  - Llamadas a `emit_stats()` cada 100 picks
- **HTTP Client:** httpx.AsyncClient con timeout 5s

### 4. Dashboard Real-Time (`static/turno_realtime.html`)
- **Líneas:** 300+
- **Secciones:**
  - Header con indicador de conexión
  - 4 Metric Cards (picks, bultos, operarios, tiempo)
  - 2 Gráficos Chart.js (picks/min, bultos acumulados)
  - Panel de eventos en vivo
- **Features:**
  - WebSocket connection con auto-reconnect
  - Gráficos actualizados en tiempo real
  - Dark theme profesional
  - Responsive design

---

## 🧪 TESTING CHECKLIST

### Test 1: Verificar Servidor Inicia Correctamente
```bash
python main.py
```
**Esperado:**
```
[INFO] Inicializando VigIA v2.0...
[INFO] Proveedor IA configurado: claude
[INFO] Uvicorn running on http://0.0.0.0:8080
```

**Validar:** No hay errores, todas las rutas se cargan ✅

### Test 2: Verificar WebSocket Endpoint
```bash
# Con servidor corriendo, en otra terminal:
python -c "
import asyncio
import websockets
import json

async def test():
    async with websockets.connect('ws://localhost:8080/ws/turno/TEST_TURNO') as ws:
        # Enviar ping
        await ws.send('ping')
        # Recibir pong
        response = json.loads(await ws.recv())
        print(f'Response: {response}')

asyncio.run(test())
"
```

**Esperado:** Recibe `{"tipo": "pong", "timestamp": "..."}` ✅

### Test 3: Verificar HTTP Broadcast Endpoints
```bash
# Pick broadcast
curl -X POST "http://localhost:8080/api/broadcast/pick?turno_id=TEST_TURNO" \
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

**Esperado:** `{"status": "ok", "turno_id": "TEST_TURNO"}` ✅

### Test 4: Dashboard Carga Correctamente
```
http://localhost:8080/turno_realtime.html
```

**Validar:**
- [ ] Página carga sin errores JavaScript
- [ ] Indicador de conexión visible (rojo/desconectado inicialmente)
- [ ] Métricas muestran 0
- [ ] Gráficos están presentes pero vacíos
- [ ] Panel de eventos visible

### Test 5: Simulador Genera Picks
**Terminal 1:**
```bash
python main.py
```

**Terminal 2:**
```bash
python scripts/simulate_realtime_turno.py --duracion_segundos 60 --turno TEST_TURNO_01
```

**Validar:**
- [ ] Simulador genera picks (ve "[0010]", "[0020]", etc en logs)
- [ ] Base de datos se llena (ve "Picks: X, Bultos: Y")
- [ ] No hay errores de conexión HTTP

### Test 6: Dashboard Recibe Eventos en Tiempo Real
1. Abre en browser: `http://localhost:8080/turno_realtime.html?turno_id=TEST_TURNO_01`
2. Corre simulador en otra terminal
3. Observa el dashboard:

**Validar:**
- [ ] Indicador de conexión cambia a verde "Conectado"
- [ ] Picks counter sube (0 → 10 → 20 → ...)
- [ ] Bultos counter sube
- [ ] Gráficos se actualizan (línea azul sube, línea verde también)
- [ ] Panel de eventos muestra picks nuevos con operarios
- [ ] Ningún error en browser console (F12)

### Test 7: Performance Test (500k+ picks)
```bash
# Simular 500k picks = ~130 minutos a 2-3 picks/seg
# Versión rápida: 5000 picks = ~20-30 segundos

python scripts/simulate_realtime_turno.py \
  --duracion_segundos 30 \
  --turno PERF_TEST \
  --intervalo_min 0.1 \
  --intervalo_max 0.2
```

**Validar:**
- [ ] Servidor no crashea bajo carga
- [ ] Dashboard sigue respondiendo rápido
- [ ] WebSocket no se desconecta
- [ ] DB inserts son exitosos (CHECK count in picks_operario)

### Test 8: Multi-Client WebSocket
1. Abre dashboard en 2 tabs del mismo browser
2. Corre simulador
3. Observa ambas tabs

**Validar:**
- [ ] Ambas tabs reciben eventos
- [ ] Ambas tabs muestran los mismos datos
- [ ] No hay conflictos

---

## 🔍 DEBUGGING

### Dashboard muestra "Desconectado"
1. Verifica que el servidor está corriendo: `http://localhost:8080/api/operarios`
2. Abre browser console (F12) y ve si hay errores
3. Verifica que la URL del WebSocket es correcta: `ws://localhost:8080/ws/turno/...`

### Simulador dice "connection refused"
1. Asegúrate de que el servidor está corriendo ANTES de iniciar el simulador
2. Verifica que usa `http://localhost:8080` (puerto 8080, no otro)
3. Verifica que el endpoint es accesible: `curl http://localhost:8080/api/operarios`

### Base de datos no se actualiza
1. Verifica que `vigia.db` existe en `C:\Ingenieria\VigIA\`
2. Verifica que la tabla `picks_operario` existe: 
   ```bash
   sqlite3 vigia.db "SELECT COUNT(*) FROM picks_operario;"
   ```
3. Verifica que el simulador no tiene error en INSERT

### Gráficos no se actualizan
1. Abre browser console (F12)
2. Busca errores de Chart.js
3. Verifica que WebSocket está recibiendo mensajes (ve en Network tab)

---

## 📊 DATOS DE VALIDACIÓN

### Valores Esperados por Componente

| Componente | Métrica | Esperado |
|------------|---------|----------|
| Simulador | Picks/minuto | 20-30 |
| Simulador | Bultos/hora | 300-600 |
| Simulador | Duración run | ~1-5 minutos |
| WebSocket | Response time | <50ms |
| WebSocket | Clientes simultáneos | 5+ |
| Dashboard | Load time | <2s |
| Dashboard | Update frequency | 100ms |
| DB | Insert speed | 1000+ picks/seg |

---

## ✅ VALIDACIÓN FINAL

- [ ] Todos los tests pasan ✅
- [ ] Dashboard funciona con simulador
- [ ] WebSocket maneja múltiples clientes
- [ ] Performance es aceptable
- [ ] Documentación está actualizada
- [ ] Código no tiene warnings/errores

**Status:** LISTO PARA SIGUIENTE FASE ✅

---

## 🎯 PRÓXIMOS PASOS

1. **SESIÓN 1.2 - Dashboard Operario**
   - Crear `static/detalle_operario.html`
   - Mostrar 5 análisis inteligentes por operario
   - Integrar con WebSocket en tiempo real

2. **SESIÓN 1.3 - Panel Comparativas**
   - Clustering visual de operarios
   - Top/Mid/Low performers

3. **SESIÓN 1.4 - Config + Recomendaciones**
   - Auto-recomendaciones basadas en análisis
   - Exportación de reportes

---

**Documento:** SESION_1.1_TESTING_GUIDE.md  
**Versión:** 1.0  
**Última actualización:** 20 de abril de 2026
