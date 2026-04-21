# VigIA API - Documentación de Endpoints

**Versión:** 2.0.0  
**Fecha:** 20 de abril de 2026  
**Base URL:** `http://localhost:8080/api`

---

## 📋 Índice

1. [Operarios](#operarios)
2. [Análisis Inteligente](#análisis-inteligente)
3. [Turnos y Olas](#turnos-y-olas)
4. [Códigos de Respuesta](#códigos-de-respuesta)

---

## Operarios

### GET /api/operarios

Lista todos los operarios del sistema con estadísticas rápidas.

**Respuesta:**
```json
{
  "total_operarios": 10,
  "operarios": [
    {
      "operario_id": "OP_00045",
      "nombre": "María López",
      "zona_principal": "Secos",
      "total_picks": 51200,
      "velocidad_promedio_seg": 28.5
    }
  ]
}
```

---

### GET /api/operarios/{operario_id}

Información detallada de un operario incluyendo histórico de picks.

**Parámetros:**
- `operario_id` (path): ID del operario (ej: OP_00045)

**Respuesta:**
```json
{
  "operario_id": "OP_00045",
  "nombre": "María López",
  "zona_principal": "Secos",
  "estadisticas": {
    "total_picks": 51200,
    "velocidad_promedio_seg": 28.5,
    "mejor_tiempo_seg": 5,
    "peor_tiempo_seg": 180,
    "tasa_error_pct": 3.2
  },
  "ultimos_picks": [
    {
      "pick_id": "PICK_00000001",
      "fecha": "2026-04-20",
      "timestamp": "2026-04-20T18:45:30",
      "ola_id": "OLA_1",
      "sku": "SKU000142",
      "tiempo_segundos": 25,
      "estado": "completado"
    }
  ],
  "picks_por_zona": [
    {"zona": "Secos", "cantidad": 40000},
    {"zona": "NOA", "cantidad": 11200}
  ]
}
```

**Ejemplo:**
```bash
curl http://localhost:8080/api/operarios/OP_00045
```

---

## Análisis Inteligente

### GET /api/operarios/{operario_id}/analisis/caida_progresiva

Detecta si el operario está experimentando fatiga durante la ola.

**Parámetros:**
- `operario_id` (path): ID del operario
- `ola_id` (query, requerido): ID de la ola a analizar

**Respuesta cuando detecta fatiga:**
```json
{
  "operario_id": "OP_00045",
  "ola_id": "OLA_1_TARDE_20_04",
  "tipo": "caida_progresiva",
  "detectado": true,
  "caida_pct": 18.5,
  "velocidad_inicial_pick_min": 2.4,
  "velocidad_final_pick_min": 1.96,
  "picks_analizados": 120,
  "severidad": "ALTA",
  "recomendacion": "Sugerir pausa preventiva próxima hora"
}
```

**Severidad:**
- `CRITICA` (>20%): Ofrecer pausa INMEDIATA
- `ALTA` (15-20%): Sugerir pausa preventiva
- `MEDIA` (10-15%): Monitorear próximas olas
- `BAJA` (<10%): Sin acción

**Ejemplo:**
```bash
curl "http://localhost:8080/api/operarios/OP_00045/analisis/caida_progresiva?ola_id=OLA_1_TARDE_20_04"
```

---

### GET /api/operarios/{operario_id}/analisis/correlacion_sku

Identifica SKUs donde el operario es experto o débil.

**Parámetros:**
- `operario_id` (path): ID del operario
- `dias` (query, opcional, default=30): Últimos N días a analizar

**Respuesta:**
```json
{
  "operario_id": "OP_00045",
  "tipo": "correlacion_sku_operario",
  "periodo_dias": 30,
  "velocidad_promedio_seg": 28.5,
  "skus_expertos": [
    {
      "sku": "SKU000142",
      "picks": 45,
      "velocidad_seg": 15.2,
      "ventaja_pct": 46.7
    },
    {
      "sku": "SKU000856",
      "picks": 32,
      "velocidad_seg": 18.5,
      "ventaja_pct": 35.1
    }
  ],
  "skus_debiles": [
    {
      "sku": "SKU001925",
      "picks": 28,
      "velocidad_seg": 42.3,
      "debilidad_pct": 48.4
    }
  ],
  "especialidad_pct": 32.5,
  "recomendacion": "Asignar preferentemente a SKUs expertos para maximizar productividad"
}
```

**Interpretación:**
- **SKUs expertos**: >20% más rápido que promedio del operario
- **SKUs débiles**: >20% más lento que promedio
- **Especialidad %**: Porcentaje de picks en SKUs donde es experto

**Ejemplo:**
```bash
curl "http://localhost:8080/api/operarios/OP_00045/analisis/correlacion_sku?dias=30"
```

---

### GET /api/operarios/{operario_id}/analisis/patron_semanal

Analiza cómo varía la productividad por día de semana.

**Parámetros:**
- `operario_id` (path): ID del operario

**Respuesta:**
```json
{
  "operario_id": "OP_00045",
  "tipo": "patron_semanal",
  "detectado": true,
  "velocidad_por_dia": [
    {
      "dia": "Lunes",
      "velocidad_seg": 24.1,
      "picks": 1200,
      "mejor_tiempo_seg": 5,
      "peor_tiempo_seg": 180
    },
    {
      "dia": "Viernes",
      "velocidad_seg": 29.5,
      "picks": 980,
      "mejor_tiempo_seg": 6,
      "peor_tiempo_seg": 175
    }
  ],
  "dia_mas_fuerte": "Lunes",
  "dia_mas_debil": "Viernes",
  "variacion_pct": 22.2,
  "recomendacion": "Patrón detectado: máxima productividad Lunes, evaluar factores externos en Viernes"
}
```

**Uso:**
- Identificar cuellos de botella por día
- Planificar mantenimiento en días débiles
- Aprovechar energía alta los lunes

**Ejemplo:**
```bash
curl http://localhost:8080/api/operarios/OP_00045/analisis/patron_semanal
```

---

### GET /api/operarios/{operario_id}/analisis/recuperacion_pausa

Analiza el impacto de pausas en la recuperación de velocidad.

**Parámetros:**
- `operario_id` (path): ID del operario

**Respuesta:**
```json
{
  "operario_id": "OP_00045",
  "tipo": "recuperacion_pausa",
  "detectado": true,
  "pausas_analizadas": 45,
  "pausas_efectivas": 32,
  "promedio_recuperacion_pct": 28.5,
  "mejor_tipo_pausa": "almuerzo",
  "detalle_pausas": [
    {
      "tipo_pausa": "almuerzo",
      "duracion_minutos": 30,
      "velocidad_pre_seg": 32.5,
      "velocidad_post_seg": 24.1,
      "recuperacion_pct": 25.8,
      "efectivo": true
    }
  ],
  "recomendacion": "Pausas de almuerzo de 30 min recomendadas"
}
```

**Interpretación:**
- **Recuperación %**: Porcentaje de mejora en velocidad post-pausa
- **Pausas efectivas**: Aquellas que mejoraron velocidad >10%
- **Mejor tipo**: Qué tipo de pausa es más efectivo para este operario

**Ejemplo:**
```bash
curl http://localhost:8080/api/operarios/OP_00045/analisis/recuperacion_pausa
```

---

### GET /api/operarios/{operario_id}/analisis/anomalia_zscore

Detecta anomalías usando desviación estándar (Z-score).

**Parámetros:**
- `operario_id` (path): ID del operario
- `ola_id` (query, opcional): Analizar solo una ola específica

**Respuesta:**
```json
{
  "operario_id": "OP_00045",
  "tipo": "anomalia_zscore",
  "detectado": true,
  "velocidad_promedio_seg": 28.1,
  "desv_estandar_seg": 5.3,
  "picks_analizados": 500,
  "picks_anomalos": 12,
  "porcentaje_anomalas": 2.4,
  "razon_probable": "Variación excepcional - investigar contexto",
  "muestra_anomalias": [
    {
      "indice": 45,
      "tiempo_seg": 85,
      "z_score": 2.34,
      "tipo": "lento"
    }
  ],
  "confianza_pct": 85.0
}
```

**Interpretación:**
- **Z-Score > 2**: Pick está >2 desviaciones estándar del promedio
- **Razon probable**:
  - "Enfermedad, fatiga severa o problema de equipamiento" si promedio_anomalas > 1.5x promedio
  - "Variación excepcional" si distribución normal

**Ejemplo:**
```bash
# Análisis general del operario
curl http://localhost:8080/api/operarios/OP_00045/analisis/anomalia_zscore

# Análisis específico de una ola
curl "http://localhost:8080/api/operarios/OP_00045/analisis/anomalia_zscore?ola_id=OLA_1_TARDE_20_04"
```

---

### GET /api/operarios/{operario_id}/analisis/completo

Ejecuta los 5 análisis inteligentes en una sola llamada.

**Parámetros:**
- `operario_id` (path): ID del operario
- `ola_id` (query, opcional): Limitar análisis a una ola

**Respuesta:**
```json
{
  "operario_id": "OP_00045",
  "ola_id": "OLA_1_TARDE_20_04",
  "timestamp": "2026-04-20T16:38:30.204085",
  "analisis": {
    "caida_progresiva": {...},
    "correlacion_sku_operario": {...},
    "patron_semanal": {...},
    "recuperacion_pausa": {...},
    "anomalia_zscore": {...}
  }
}
```

**Caso de uso:** Dashboard de operario mostrando análisis completo.

**Ejemplo:**
```bash
curl "http://localhost:8080/api/operarios/OP_00045/analisis/completo?ola_id=OLA_1_TARDE_20_04"
```

---

## Turnos y Olas

### GET /api/olas

Lista todas las olas del turno actual o especificado.

**Parámetros:**
- `turno_id` (query, opcional): ID del turno (si no se especifica, usa turno en curso)

**Respuesta:**
```json
[
  {
    "ola_id": "OLA_1_TARDE_20_04",
    "numero_ola": 1,
    "zona": "Secos",
    "hora_inicio": "14:00",
    "hora_fin": "14:30",
    "bultos_programados": 500,
    "bultos_ejecutados": 485,
    "pct_ejecucion": 97.0,
    "estado": "en_curso",
    "operarios_asignados": 20
  }
]
```

---

### GET /api/olas/{ola_id}/operarios

Operarios asignados a una ola con productividad.

**Respuesta:**
```json
[
  {
    "asignacion_id": "ASG_001",
    "operario_id": "OP_00045",
    "nombre": "María López",
    "bultos_programados": 50,
    "bultos_reales": 48,
    "productividad": 235,
    "estandar": 250,
    "desvio_pct": -6.0,
    "estado_productividad": "bajo",
    "estado": "activo"
  }
]
```

---

### GET /api/olas/{ola_id}/alertas

Alertas generadas para una ola basadas en productividad.

**Respuesta:**
```json
{
  "ola_id": "OLA_1_TARDE_20_04",
  "cantidad_alertas": 3,
  "alertas_criticas": 1,
  "alertas_altas": 1,
  "alertas": [
    {
      "operario_id": "OP_00045",
      "operario_nombre": "María López",
      "tipo": "productividad_baja",
      "desvio_pct": -26.0,
      "productividad": 185,
      "estandar": 250,
      "severidad": "CRITICA"
    }
  ]
}
```

---

### GET /api/olas/{ola_id}/comparativas

Top performers y bottom performers de una ola.

**Respuesta:**
```json
{
  "ola_id": "OLA_1_TARDE_20_04",
  "top_performers": [
    {
      "operario_id": "OP_00001",
      "operario_nombre": "Juan García",
      "productividad": 285,
      "bultos_reales": 57,
      "posicion": 1
    }
  ],
  "bottom_performers": [
    {
      "operario_id": "OP_00045",
      "operario_nombre": "María López",
      "productividad": 185,
      "bultos_reales": 37,
      "posicion": 10
    }
  ]
}
```

---

## Códigos de Respuesta

| Código | Significado | Ejemplo |
|--------|------------|---------|
| 200 | OK - Respuesta exitosa | Consulta de operario exitosa |
| 400 | Bad Request - Parámetro inválido | ola_id no existe |
| 404 | Not Found - Recurso no encontrado | operario_id no existe |
| 500 | Server Error - Error del servidor | Error de base de datos |

---

## Ejemplos de Uso Completo

### 1. Dashboard Operario
```bash
# Obtener análisis completo
curl http://localhost:8080/api/operarios/OP_00045/analisis/completo

# Parsear JSON y mostrar en dashboard
```

### 2. Monitoreo en Tiempo Real
```bash
# Cada 30 segundos
curl http://localhost:8080/api/operarios/OP_00045/analisis/anomalia_zscore?ola_id=OLA_1_TARDE_20_04

# Si detecta anomalía, enviar alerta a supervisor
```

### 3. Análisis de Performance
```bash
# Obtener todos los operarios
curl http://localhost:8080/api/operarios

# Para cada operario, obtener análisis completo
for op in operarios; do
  curl http://localhost:8080/api/operarios/$op/analisis/completo
done
```

### 4. Optimización de Asignación
```bash
# Obtener correlación SKU para operario
curl "http://localhost:8080/api/operarios/OP_00045/analisis/correlacion_sku"

# Usar skus_expertos para asignar próximos picks
```

---

## Notas de Performance

- Todas las respuestas son JSON
- Los análisis son **cachéables** (resultado no cambia en 60 segundos)
- Para operarios con >10k picks, el análisis tarda ~500ms
- Usar índices de BD para queries rápidas

---

## Próximos Endpoints (SESIÓN 1.2)

- `POST /api/recomendaciones` - Generar recomendaciones automáticas
- `WebSocket /ws/operarios/{operario_id}` - Análisis en tiempo real
- `GET /api/reportes/{tipo}` - Exportar reportes
