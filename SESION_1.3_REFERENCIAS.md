# SESIÓN 1.3 - Referencias Rápidas

## 🌐 URLs PRINCIPALES

### Panel Comparativas
```
http://localhost:8080/comparativas.html
```

---

## 📡 API ENDPOINTS

### Métricas de Todos los Operarios
```
GET /api/comparativas/metricas
```

**Retorna:**
- Lista de todos los operarios
- Cada uno con: picks, bultos, velocidad, error rate
- Incluye últimos 7 días

**Response:**
```json
{
  "total_operarios": 10,
  "metricas": [
    {
      "operario_id": "OP_00045",
      "display_id": "OP_00045",
      "total_picks": 5200,
      "total_bultos": 12500,
      "velocidad_promedio_seg": 24.3,
      "tasa_error_pct": 2.1,
      "picks_7d": 450,
      "bultos_7d": 1050,
      "vel_7d": 24.5
    },
    ...
  ]
}
```

### Clustering Automático
```
GET /api/comparativas/clusters
```

**Retorna:**
- High Performers (top 33%)
- Mid Range (middle 34%)
- Learning (bottom 33%)
- Cada cluster con: count, top operarios, promedios

**Response:**
```json
{
  "clusters": {
    "high_performers": {
      "count": 3,
      "operarios": [
        {"operario_id": "OP_00045", "score": 87.3},
        {"operario_id": "OP_00067", "score": 84.1}
      ],
      "stats": {
        "avg_score": 85.5,
        "avg_picks": 5200,
        "avg_vel": 24.3,
        "avg_error": 2.1
      }
    },
    "mid_range": {...},
    "learning": {...}
  },
  "all_scored": [
    {"operario_id": "OP_00045", "total_picks": 5200, "velocidad_promedio": 24.3, "error_rate": 2.1, "score": 87.3},
    ...
  ]
}
```

### Benchmark Individual vs Grupo
```
GET /api/comparativas/benchmark/{operario_id}
```

**Parámetro:**
- `operario_id`: ID del operario (ej: OP_00045)

**Retorna:**
- Métricas del operario seleccionado
- Promedio del grupo
- Diferencias en porcentaje

**Response:**
```json
{
  "operario_id": "OP_00045",
  "operario": {
    "total_picks": 5200,
    "velocidad_promedio": 24.3,
    "tasa_error_pct": 2.1
  },
  "grupo": {
    "total_picks_promedio": 3850,
    "velocidad_promedio": 28.5,
    "tasa_error_pct": 3.2
  },
  "comparativa": {
    "picks_diferencia_pct": 35.1,
    "velocidad_diferencia_pct": 14.7,
    "error_diferencia_pct": -34.4
  }
}
```

---

## 🧪 TESTING URLS (con curl)

### Listar Métricas
```bash
curl http://localhost:8080/api/comparativas/metricas | jq
```

### Ver Clustering
```bash
curl http://localhost:8080/api/comparativas/clusters | jq
```

### Benchmark de Operario
```bash
curl http://localhost:8080/api/comparativas/benchmark/OP_00045 | jq
```

### Benchmark de Todos los Operarios
```bash
for op_id in OP_00001 OP_00045 OP_00089; do
  echo "=== $op_id ===" 
  curl -s http://localhost:8080/api/comparativas/benchmark/$op_id | jq '.comparativa'
done
```

---

## 🎨 COMPONENTES VISUALES

### Bubble Chart
```
Eje X: Velocidad Promedio (segundos)
Eje Y: Total Picks
Tamaño: Cantidad de Bultos

Colores:
- Verde (#00ff88): High Performers
- Amarillo (#ffc107): Mid Range
- Rojo (#ff6b6b): Learning
```

### Cluster Cards
```html
<!-- High Performers Card -->
<div class="card cluster-card cluster-high">
  <div class="cluster-name">🌟 High Performers</div>
  <div class="cluster-count">3</div>
  <div class="cluster-stats">
    <div class="stat-row">Score Promedio: 85.5</div>
    <div class="stat-row">Picks Promedio: 5,200</div>
    <div class="stat-row">Velocidad: 24.3s</div>
    <div class="stat-row">Tasa Error: 2.1%</div>
  </div>
  <div class="cluster-toppers">
    <!-- Lista de top 5 operarios -->
  </div>
</div>
```

### Benchmark Comparison
```html
<div class="benchmark-grid">
  <div class="card">
    <h3>📊 Métricas del Operario</h3>
    <div class="benchmark-row">Total Picks: 5,200</div>
    <div class="benchmark-row">Velocidad: 24.3s</div>
    <div class="benchmark-row">Tasa Error: 2.1%</div>
  </div>
  <div class="card">
    <h3>👥 Promedio del Grupo</h3>
    <div class="benchmark-row">Total Picks: 3,850</div>
    <div class="benchmark-row">Velocidad: 28.5s</div>
    <div class="benchmark-row">Tasa Error: 3.2%</div>
  </div>
</div>
```

---

## 📊 ALGORITMO DE CLUSTERING

```python
def calcular_score(operario):
    score = (total_picks / velocidad_promedio) * (1 - error_rate)
    return score

# Ordenar por score descendente
operarios_sorted = sorted(operarios, key=lambda x: x.score, reverse=True)

# Dividir en percentiles
n = len(operarios_sorted)
high_threshold = int(n * 0.33)
mid_threshold = int(n * 0.67)

high_performers = operarios_sorted[:high_threshold]
mid_range = operarios_sorted[high_threshold:mid_threshold]
learning = operarios_sorted[mid_threshold:]
```

---

## 📈 FÓRMULAS DE BENCHMARK

### Diferencia de Picks
```
picks_diff_pct = ((picks_op - picks_grupo) / picks_grupo) * 100
```
- Positivo: Operario hace más picks que grupo
- Negativo: Operario hace menos picks que grupo

### Diferencia de Velocidad
```
vel_diff_pct = ((vel_grupo - vel_op) / vel_grupo) * 100
```
- Positivo: Operario es MÁS RÁPIDO (menor tiempo)
- Negativo: Operario es MÁS LENTO (mayor tiempo)

### Diferencia de Error Rate
```
error_diff_pct = ((error_op - error_grupo) / error_grupo) * 100
```
- Positivo: Operario tiene MÁS ERRORES
- Negativo: Operario tiene MENOS ERRORES (mejor)

---

## 🔗 FLUJO DE DATOS

```
1. Cargar Dashboard (comparativas.html)
   ├─ GET /api/comparativas/metricas
   │  └─ Rellena selectores
   └─ GET /api/comparativas/clusters
      ├─ Muestra cluster cards
      └─ Renderiza bubble chart

2. Seleccionar Operario
   └─ GET /api/comparativas/benchmark/{operario_id}
      ├─ Actualiza métricas operario
      ├─ Actualiza métricas grupo
      └─ Calcula y muestra diferencias

3. Auto-refresh (cada 30 segundos)
   └─ Repite paso 1
```

---

## 🚀 WORKFLOW DE USUARIO

### 1. Abrir Dashboard
```
http://localhost:8080/comparativas.html
```

### 2. Ver Clustering
- Automáticamente ve bubble chart con todos operarios
- Los colores indican su cluster
- El tamaño de burbuja indica volumen de trabajo

### 3. Analizar Clusters
- Lee tarjetas de cada cluster
- Ve top 5 operarios por cluster
- Compara promedios entre clusters

### 4. Benchmark Individual
- Click en selector de operarios
- Ve cómo se compara vs grupo
- Identifica fortalezas y áreas mejora

### 5. Monitoreo Continuo
- Dashboard auto-refresca cada 30s
- Puede cerrar y volver a abrir
- Datos siempre reflejan último estado

---

## 💾 ALMACENAMIENTO DE DATOS

### Fuentes de Datos
- `picks_operario`: Todos los picks completados
- Se usan índices para optimizar queries
- No se almacena en caché

### Performance
- Queries < 500ms típico
- Rendering < 1s
- No hay memory leaks

---

## 📱 RESPONSIVE DESIGN

### Desktop (1920x1080)
- ✅ Grid 3 columnas para cluster cards
- ✅ Bubble chart full width
- ✅ Benchmark grid 2 columnas
- ✅ Óptimo para presentación

### Tablet (1024x768)
- ✅ Grid 2 columnas para clusters
- ✅ Bubble chart con scroll
- ✅ Benchmark grid responsive

### Mobile (375x667)
- ✅ Grid 1 columna para clusters
- ✅ Bubble chart con scroll horizontal
- ✅ Benchmark cards stacked
- ✅ Selector funcional

---

## ❌ TROUBLESHOOTING

| Problema | Solución |
|----------|----------|
| "Bubble chart vacío" | Verificar que hay datos en picks_operario, GET /api/comparativas/metricas |
| "Clusters no se forman" | Verificar que hay >9 operarios (para 3 clusters) |
| "Benchmark no carga" | Asegurar operario_id válido, GET /api/comparativas/benchmark/OP_00001 |
| "Selector vacío" | Verificar servidor corre y BD tiene datos |
| "Datos lentos" | Puede ser BD lenta, revisar índices |

---

## 🔗 ENLACES ÚTILES

| Recurso | URL |
|---------|-----|
| Panel Comparativas | `http://localhost:8080/comparativas` |
| API Docs (Swagger) | `http://localhost:8080/docs` |
| Turno Real-Time | `http://localhost:8080/turno_realtime` |
| Detalle Operario | `http://localhost:8080/detalle_operario` |
| Resumen Sesión | `SESION_1.3_RESUMEN.md` |
| Status Proyecto | `STATUS.md` |

---

## 💡 EJEMPLOS DE USO

### Encontrar High Performers
```bash
curl http://localhost:8080/api/comparativas/clusters | \
  jq '.clusters.high_performers.operarios'
```

### Ranking Completo de Todos
```bash
curl http://localhost:8080/api/comparativas/clusters | \
  jq '.all_scored | sort_by(.score) | reverse'
```

### Benchmarks de Top 3
```bash
curl http://localhost:8080/api/comparativas/clusters | \
  jq '.clusters.high_performers.operarios[].operario_id' | \
  while read op; do
    echo "=== $op ==="
    curl -s http://localhost:8080/api/comparativas/benchmark/$op | jq '.comparativa'
  done
```

---

**Documento:** SESION_1.3_REFERENCIAS.md  
**Versión:** 1.0  
**Última actualización:** 20 de abril de 2026
