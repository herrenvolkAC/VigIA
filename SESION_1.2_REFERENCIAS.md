# SESIÓN 1.2 - Referencias Rápidas

## 🌐 URLs PRINCIPALES

### Dashboard Operario
```
http://localhost:8080/detalle_operario.html
```

Con parámetro (futuro):
```
http://localhost:8080/detalle_operario.html?operario_id=OP_00045
```

### API Endpoints (Nuevos)
```
GET /api/operarios/{operario_id}/historico?dias=30
GET /api/operarios/{operario_id}/historico?dias=7     (últimos 7 días)
GET /api/operarios/{operario_id}/historico?dias=90    (últimos 90 días)
```

### API Endpoints (Existentes - Usados por Dashboard)
```
GET /api/operarios                                      → Lista operarios
GET /api/operarios/{id}                                 → Detalle
GET /api/operarios/{id}/analisis/caida_progresiva       → Análisis 1
GET /api/operarios/{id}/analisis/correlacion_sku        → Análisis 2
GET /api/operarios/{id}/analisis/patron_semanal         → Análisis 3
GET /api/operarios/{id}/analisis/recuperacion_pausa     → Análisis 4
GET /api/operarios/{id}/analisis/anomalia_zscore        → Análisis 5
```

---

## 📡 FLUJO DE DATOS

```
1. Dashboard carga
   ├─ GET /api/operarios → llena selector
   └─ Selecciona primer operario

2. Operario seleccionado
   ├─ GET /api/operarios/{id} → datos básicos
   ├─ GET .../analisis/caida_progresiva → Gráfico 1
   ├─ GET .../analisis/correlacion_sku → Gráfico 2
   ├─ GET .../analisis/patron_semanal → Gráfico 3
   ├─ GET .../analisis/recuperacion_pausa → Gráfico 4
   ├─ GET .../analisis/anomalia_zscore → Gráfico 5
   ├─ GET .../historico?dias=30 → Gráfico histórico
   └─ ws://... → Conecta WebSocket para updates

3. WebSocket Updates (en vivo)
   └─ Si pick.operario_id === operario actual
      ├─ Actualiza info cards
      ├─ Emite eventos
      └─ Redibuja gráficos (opcional)
```

---

## 📊 RESPUESTAS API

### GET /api/operarios/{id}/historico
```json
{
  "operario_id": "OP_00045",
  "periodo_dias": 30,
  "total_registros": 25,
  "historico": [
    {
      "fecha": "2026-03-20",
      "picks": 150,
      "bultos": 350,
      "velocidad_promedio": 28.5,
      "errores": 2
    },
    {
      "fecha": "2026-03-21",
      "picks": 155,
      "bultos": 365,
      "velocidad_promedio": 27.8,
      "errores": 1
    }
  ]
}
```

### Operario Info Card Data
```json
{
  "operario_id": "OP_00045",
  "nombre": "María López",
  "total_picks": 1250,
  "bultos_total": 2850,
  "velocidad_promedio": 28.5,
  "estadisticas": {
    "total_picks": 1250,
    "velocidad_promedio_seg": 28.5,
    "mejor_tiempo_seg": 15,
    "peor_tiempo_seg": 120,
    "tasa_error_pct": 3.2
  }
}
```

---

## 🧪 TESTING URLS (con curl)

### Listar Operarios
```bash
curl http://localhost:8080/api/operarios | jq
```

### Detalle Operario
```bash
curl http://localhost:8080/api/operarios/OP_00045 | jq
```

### Histórico 30 Días
```bash
curl "http://localhost:8080/api/operarios/OP_00045/historico?dias=30" | jq
```

### Histórico 7 Días
```bash
curl "http://localhost:8080/api/operarios/OP_00045/historico?dias=7" | jq
```

### Caída Progresiva
```bash
curl "http://localhost:8080/api/operarios/OP_00045/analisis/caida_progresiva?ola_id=OLA_1" | jq
```

### Todos los Análisis
```bash
curl "http://localhost:8080/api/operarios/OP_00045/analisis/completo" | jq
```

---

## 🎨 COMPONENTES VISUALES

### 5 Análisis Card Structure
```html
<div class="analisis-card">
  <div class="analisis-header">
    <div class="analisis-titulo">📉 Título</div>
    <div class="severity-badge">SEVERIDAD</div>
  </div>
  <canvas id="chart-xxx"></canvas>
  <div class="analisis-descripcion">Explicación...</div>
  <div class="analisis-datos">
    <div class="dato-item">
      <div class="dato-label">Métrica</div>
      <div class="dato-valor">Valor</div>
    </div>
  </div>
  <div class="recomendacion">Recomendación automática...</div>
</div>
```

### Severity Badges
- `<div class="severity-badge ok">NORMAL</div>`     → Verde #00ff88
- `<div class="severity-badge warning">ALERTA</div>` → Amarillo #ffc107
- `<div class="severity-badge danger">CRÍTICA</div>` → Rojo #ff4757

### Charts Types Used
- **Caída Progresiva**: `line` - velocidad en el tiempo
- **Correlación SKU**: `bar` - mejor vs normal vs débil
- **Patrón Semanal**: `line` - picks por día de semana
- **Recuperación Pausa**: `bar` - antes vs después
- **Anomalía Z-Score**: `scatter` - picks individuales
- **Histórico 30d**: `line` - dual-axis (picks + bultos)

---

## 📁 ARCHIVOS MODIFICADOS/CREADOS

### Nuevos
- `static/detalle_operario.html` (380+ líneas)
- `SESION_1.2_RESUMEN.md`
- `SESION_1.2_REFERENCIAS.md` (este archivo)

### Modificados
- `routers/operarios.py` (+50 líneas) - Endpoint histórico
- `main.py` (+3 líneas) - Ruta dashboard

---

## 🔧 JAVASCRIPT FUNCTIONS

### Cargar Datos
```javascript
cargarOperarios()              // Llena selector
cargarOperario(id)             // Carga detalle + análisis
cargarCaidaProgresiva()        // Carga análisis 1
cargarCorrelacionSKU()         // Carga análisis 2
cargarPatronSemanal()          // Carga análisis 3
cargarRecuperacionPausa()      // Carga análisis 4
cargarAnomaliaZScore()         // Carga análisis 5
cargarHistorico()              // Carga histórico 30d
```

### Actualizar Gráficos
```javascript
crearGrafico(canvasId, tipo, config)
// tipos: 'line', 'bar', 'scatter', 'bubble'

actualizarInfoCards()          // Actualiza métricas
actualizarMetricasEnVivo(pick) // Actualiza por WebSocket
```

### WebSocket
```javascript
connectWebSocket(turnoId)      // Conectar al turno
// Actualiza métricas cuando llegan picks del operario actual
```

---

## 🚀 WORKFLOW DE USUARIO

### 1. Abrir Dashboard
```
http://localhost:8080/detalle_operario.html
```

### 2. Seleccionar Operario
- Click en dropdown
- Seleccionar operario
- Dashboard carga automáticamente

### 3. Revisar Análisis
- Scroll por los 5 análisis
- Leer descripción de cada análisis
- Ver recomendación automática
- Notar severidad badges

### 4. Revisar Histórico
- Scroll al fondo
- Ver gráfico de últimos 30 días
- Identificar tendencias
- Comparar picks vs bultos

### 5. En Tiempo Real
- Si simulador está corriendo
- Ver métricas actualizarse
- Refresco automático cada pick

---

## 📈 INDICADORES DE ÉXITO

### Dashboard Carga
- [x] Página renderiza sin errores
- [x] Selector llena con operarios
- [x] Primer operario carga automáticamente

### Análisis Cargan
- [x] 5 gráficos se renderizan
- [x] Datos se muestran correctamente
- [x] Badges tienen color correcto

### Histórico Funciona
- [x] Gráfico dual-axis renderiza
- [x] Últimos 30 días se muestran
- [x] Tendencias visibles

### Performance
- [x] Página carga en <2s
- [x] Gráficos render en <500ms
- [x] Smooth responsivity

---

## ❌ TROUBLESHOOTING

| Problema | Solución |
|----------|----------|
| "Dropdown vacío" | Verificar que servidor está corriendo, `/api/operarios` responde |
| "Gráficos no renderiza" | Abrir console (F12), buscar errores de Chart.js |
| "Histórico no carga" | Asegurar que hay datos en picks_operario para ese operario |
| "WebSocket rojo" | Normal si no hay simulador, verde cuando simulador corre |
| "Datos lentos" | Verificar `/api/operarios/{id}` en browser, puede ser BD lenta |

---

## 🔗 ENLACES ÚTILES

| Recurso | URL |
|---------|-----|
| Dashboard Operario | `http://localhost:8080/detalle_operario.html` |
| Dashboard Turno | `http://localhost:8080/turno_realtime.html` |
| API Docs | `http://localhost:8080/docs` |
| Resumen Sesión | `SESION_1.2_RESUMEN.md` |
| Quick Start | `QUICK_START.md` |

---

## 💡 DATOS INTERESANTES

### Ejemplo de Respuesta Caída Progresiva
```json
{
  "detectado": true,
  "velocidad_inicial": 28.5,
  "velocidad_final": 23.2,
  "caida_pct": 18.6,
  "severidad": "ALTA",
  "recomendacion": "Ofrecerle pausa preventiva próxima hora"
}
```

### Ejemplo de Respuesta Correlación SKU
```json
{
  "skus_expertos": [
    {"sku": "SKU000142", "velocidad": 21.5, "ventaja_pct": 46.7},
    {"sku": "SKU000856", "velocidad": 23.1, "ventaja_pct": 35.1}
  ],
  "skus_debiles": [
    {"sku": "SKU001234", "velocidad": 45.2, "ventaja_pct": -58.5}
  ],
  "especialidad_pct": 32.5
}
```

---

**Documento:** SESION_1.2_REFERENCIAS.md  
**Versión:** 1.0  
**Última actualización:** 20 de abril de 2026
