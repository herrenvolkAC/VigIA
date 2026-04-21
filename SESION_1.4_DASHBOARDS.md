# 🎯 SESIÓN 1.4 - DASHBOARDS ACCESIBLES

**Status:** ✅ COMPLETADA  
**Fecha:** 20 de abril de 2026  
**MVP VigIA 3.0:** LISTO PARA DEMOSTRACIÓN

---

## 📊 Dashboards Disponibles

Después de completar SESIÓN 1.4, tienes acceso a **5 dashboards integrados** que ofrecen visibilidad completa del operativo:

### Dashboard 1: Real-Time Turno 🚀
**URL:** http://localhost:8080/turno_realtime

**Lo que ves:**
- Actualizaciones en vivo de picking por segundo
- Gráficos de velocidad en tiempo real
- Contador de picks, bultos, errores
- Tabla de operarios activos con métricas
- WebSocket connection status
- Auto-refresh automático

**Para:** Supervisores monitoreando turno actual
**Sesión:** 1.1

---

### Dashboard 2: Detalle Operario 🔍
**URL:** http://localhost:8080/detalle_operario

**Lo que ves:**
- Selector dropdown para elegir operario
- 4 info cards: total picks, velocidad, tasa error, especialidad
- 5 análisis inteligentes con gráficos:
  1. **Caída Progresiva:** Detecta fatiga del operario
  2. **Correlación SKU:** Identifica SKUs favoritos
  3. **Patrón Semanal:** Detecta variaciones por día
  4. **Recuperación Pausa:** Mide efectividad de descansos
  5. **Anomalía Z-Score:** Identifica picks raros
- Gráfico histórico 30 días (dual-axis)
- Tablas con detalles de análisis

**Para:** Supervisores analizando desempeño individual
**Sesión:** 1.2

---

### Dashboard 3: Comparativas 📊
**URL:** http://localhost:8080/comparativas

**Lo que ves:**
- **Bubble Chart:** Distribución de operarios por performance
  - Eje X: Velocidad (seg/pick)
  - Eje Y: Tasa error (%)
  - Tamaño burbuja: volumen de trabajo
  - Color: cluster (verde/amarillo/rojo)
- **3 Cluster Cards:**
  - High Performers (top 33%)
  - Mid Range (middle 34%)
  - Learning (bottom 33%)
- **Benchmark Individual:**
  - Comparar 1 operario vs grupo
  - Diferencias en %
  - Posición en cluster

**Para:** Supervisores comparando operarios y detectando patrones
**Sesión:** 1.3

---

### Dashboard 4: Config + Recomendaciones ⚙️
**URL:** http://localhost:8080/config_y_recomendaciones

**4 Tabs funcionales:**

#### Tab 1: Configuración
```
🎛️ CONFIGURACIÓN DE UMBRALES

Sliders personalizables:
├─ Caída Crítica: 20% (ajustable)
├─ Caída Alta: 15%
├─ Caída Media: 10%
├─ Error Máximo: 5%
├─ Velocidad Mínima: 28 seg
└─ Especialidad Mínima: 30%

Checkboxes para alertas:
├─ ☑️ Caída Progresiva
├─ ☑️ Tasa Error Alta
├─ ☑️ Especialización SKU
├─ ☑️ Pausa Efectiva
└─ ☑️ Anomalías

Configuración email:
├─ Email destino: supervisor@coto.com.ar
└─ Frecuencia: [Diario ▼]

Botones:
├─ [Guardar Configuración] → Persiste en backend
└─ [Restaurar Defaults] → Vuelve a valores originales
```

#### Tab 2: Recomendaciones
```
💡 RECOMENDACIONES AUTOMÁTICAS

Operario: [OP_00045 ▼]

┌──────────────────────────────────────────┐
│ 🔴 ALERTA: Fatiga Detectada              │
│ ─────────────────────────────────────    │
│ Operario pierde 22% de velocidad         │
│                                           │
│ ➤ Sugerencia: Ofrecer pausa preventiva   │
│   en próxima hora                        │
│                                           │
│ 💰 Impacto: Prevenir ~100 picks perdidos │
│                                           │
│ [Trigger Pausa]                          │
└──────────────────────────────────────────┘

┌──────────────────────────────────────────┐
│ ⭐ OPORTUNIDAD: Especialización          │
│ ─────────────────────────────────────    │
│ Operario es 35% más rápido con SKU-4521  │
│                                           │
│ ➤ Sugerencia: Aumentar asignación        │
│   de SKU-4521                            │
│                                           │
│ 💰 Impacto: +1.820 picks extra/mes       │
│                                           │
│ [Assign SKU]                             │
└──────────────────────────────────────────┘

┌──────────────────────────────────────────┐
│ ☕ OPORTUNIDAD: Pausas Estratégicas      │
│ ─────────────────────────────────────    │
│ Post-pausa almuerzo: +28% velocidad      │
│                                           │
│ ➤ Sugerencia: Aumentar pausas almuerzo  │
│                                           │
│ 💰 Impacto: +250 picks/turno con 2 pausas│
│                                           │
│ [Schedule Pausa]                         │
└──────────────────────────────────────────┘
```

**Lo que hacen las recomendaciones:**
- Sintetizan los 5 análisis en acciones concretas
- Calculan impacto estimado cuantificado
- Ordenan por severidad
- Permiten ejecutar acción directamente
- Se actualizan dinámicamente por operario

#### Tab 3: Alertas
```
🚨 ALERTAS ACTIVAS (últimas 24h)

[Auto-refresh: cada 10 segundos]

🔴 CRÍTICA - 14:30 - OP_00045
   Tasa error 6.2% (esperado: 2-3%)
   ➤ Revisar con operario

🟡 ALTA - 13:15 - OP_00067
   Caída 18% de velocidad
   ➤ Ofrecer pausa preventiva

🟢 POSITIVO - 12:00 - OP_00023
   Recuperación 28% post-pausa
   ➤ Aumentar pausas almuerzo

⚪ INFO - 11:45 - OP_00089
   Variación semanal 16%
   ➤ Rebalancear carga semanal
```

**Características:**
- Auto-refresh cada 10 segundos
- Badges de severidad con colores
- Timestamp exacto de cada alerta
- Acción sugerida para cada una

#### Tab 4: Reportes
```
📄 GENERACIÓN DE REPORTES

Tipo: [Diario ▼]

Formatos:
☑️ JSON (descargable)
☑️ PDF (con gráficos)
☑️ Excel (con datos)

[Generar Reporte]

─────────────────────────────
REPORTES RECIENTES
─────────────────────────────
• Diario 2026-04-20.json  (125 KB)
• Diario 2026-04-19.pdf   (450 KB)
• Semanal 2026-04-19.xlsx (200 KB)
```

**Lo que incluye cada reporte:**
- Resumen: total operarios, picks, bultos
- Ranking top 10 operarios
- Métricas: velocidad, errores, especialidad
- Formato: JSON (datos crudos), PDF (visual), Excel (análisis)

**Para:** Supervisores configurando sistema, viendo recomendaciones y generando reportes
**Sesión:** 1.4

---

### Dashboard 5: Picking (Existente) 📦
**URL:** http://localhost:8080/picking

**Lo que ves:**
- Sistema picking principal existente
- Captura de eventos de picking
- Registro de SKUs, cantidades, operarios

**Para:** Operarios registrando picks en turno
**Sesión:** Previo a 1.0

---

## 🔄 Flujo Típico de Uso

### Mañana - Supervisor prepara turno (5 min)
```
1. Abre http://localhost:8080/config_y_recomendaciones
2. Tab "Configuración": Revisa umbrales
3. Ajusta si es necesario (ej: error_maximo 5% → 6%)
4. Clickea "Guardar Configuración"
```

### Turno - Monitor en vivo (durante picking)
```
1. Abre http://localhost:8080/turno_realtime
2. Gráficos actualizándose en tiempo real
3. Ve alertas conforme aparecen
4. Interviene rápidamente si hay problemas
```

### Turno - Análisis individual (cuando hay problema)
```
1. Detalla problema con operario OP_00045
2. Abre http://localhost:8080/detalle_operario
3. Selecciona OP_00045
4. Ve los 5 análisis inteligentes
5. Toma decisión: ¿pausa? ¿cambio de zona? ¿otro SKU?
```

### Turno - Recomendaciones automáticas
```
1. Abre http://localhost:8080/config_y_recomendaciones
2. Tab "Recomendaciones"
3. Selecciona OP_00045
4. Ve automáticamente sugerencias accionables
5. Clickea "Trigger Pausa" o "Assign SKU"
```

### Fin turno - Reportes (5 min)
```
1. Abre http://localhost:8080/config_y_recomendaciones
2. Tab "Reportes"
3. Tipo: "Diario"
4. Formatos: PDF + Excel
5. Clickea "Generar Reporte"
6. Descarga ambos archivos
7. Envía por email a gerencia
```

---

## 📈 Datos Que Ves

### De los 5 Análisis Inteligentes:
- **Caída Progresiva:** Velocidad inicial vs final, porcentaje caída
- **Correlación SKU:** SKU favorito, velocidad promedio, ventaja %
- **Patrón Semanal:** Día más productivo, día más lento, variación %
- **Recuperación Pausa:** Tipo de pausa más efectiva, mejora %
- **Anomalía Z-Score:** Cantidad picks raros, porcentaje, causas probables

### De Comparativas:
- Clustering automático en 3 grupos (High/Mid/Learning)
- Posición en bubble chart (velocidad vs error)
- Comparativa individual vs grupo
- Diferencias en % (picks, velocidad, error)

### De Config:
- 6 umbrales personalizables por CD
- 5 tipos de alertas habilitables
- Email y frecuencia de reporte

---

## 🎨 Características de UX

### Diseño
- Dark theme profesional (gris + cian)
- Responsive: desktop/tablet/mobile
- Tabs funcionales y claros
- Cards con información agrupada
- Badges de severidad con colores

### Interactividad
- Sliders con valor en tiempo real
- Dropdowns dinámicos de operarios
- Buttons con estados (normal/hover/active)
- Loading spinners en fetch
- Auto-refresh en alertas

### Accesibilidad
- Labels en inputs
- Tab navigation funcional
- Contraste de colores adecuado
- Fuentes legibles

---

## 🔗 API Endpoints Detrás de los Dashboards

Cada dashboard consume 1+ endpoints:

### turno_realtime.html
- WebSocket: `ws://localhost:8080/ws/turno/{turno_id}`
- REST: `POST /api/broadcast/pick`, `POST /api/broadcast/stats`

### detalle_operario.html
- `GET /api/operarios`
- `GET /api/operarios/{id}`
- `GET /api/operarios/{id}/analisis/*` (5 análisis)
- `GET /api/operarios/{id}/historico`

### comparativas.html
- `GET /api/comparativas/metricas`
- `GET /api/comparativas/clusters`
- `GET /api/comparativas/benchmark/{operario_id}`

### config_y_recomendaciones.html
- `GET /api/operarios` (para selector)
- `GET /api/recomendaciones/{operario_id}`
- `GET /api/alertas?dias=1`
- `POST /api/config/guardar`
- `GET /api/reportes/generar?formato=json`

---

## 📊 Datos de Ejemplo

### Recomendaciones retornadas para OP_00045:
```
{
  "operario_id": "OP_00045",
  "total_recomendaciones": 3,
  "recomendaciones": [
    {
      "tipo": "caida_progresiva",
      "titulo": "🔴 ALERTA: Fatiga Detectada",
      "severidad": "CRÍTICA",
      "descripcion": "Operario pierde 22% de velocidad",
      "recomendacion": "Ofrecer pausa preventiva",
      "impacto": "Prevenir ~100 picks perdidos",
      "accionable": true
    },
    ...
  ]
}
```

---

## ✅ Validación

Todo está listo:
- ✅ Dashboards accesibles
- ✅ APIs respondiendo
- ✅ Data flowing correctamente
- ✅ UI responsive
- ✅ Documentación completa

---

## 🚀 Próxima Fase

Después de validar con usuarios:

**FASE 2:** Captura de Eventos + Root Cause
- Dashboard con timeline de eventos operativos
- Root cause detection automático
- Correlación eventos con cambios de productividad

**FASE 3:** Simulador What-If
- Simular escenarios (mover operarios, cambiar velocidad)
- Ver impacto estimado
- Dashboard por zonas

**FASE 4:** ML Predictive
- Modelo de predicción de productividad
- Alertas predictivas
- Dashboard operario mejorado

---

**MVP VigIA 3.0 Completado** ✅  
**Listos para Demostración** 🎯  
**5 Dashboards Funcionales** 🚀
