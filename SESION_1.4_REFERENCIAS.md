# 📚 SESIÓN 1.4 - REFERENCIAS RÁPIDAS

**Última actualización:** 20 de abril de 2026

---

## 🌐 URLs Principales

| Página | URL | Descripción |
|--------|-----|-------------|
| Dashboard Config | `http://localhost:8080/config_y_recomendaciones` | Configuración + Recomendaciones |
| Alt. HTML | `http://localhost:8080/config_y_recomendaciones.html` | Mismo archivo |
| Dashboard Turno | `http://localhost:8080/turno_realtime` | Real-time picking |
| Dashboard Operario | `http://localhost:8080/detalle_operario` | Análisis por operario |
| Comparativas | `http://localhost:8080/comparativas` | Clustering + benchmark |
| API Docs | `http://localhost:8080/docs` | Swagger UI |
| ReDoc | `http://localhost:8080/redoc` | ReDoc documentation |

---

## 📡 Endpoints API (Nuevos en 1.4)

### 1. GET /api/recomendaciones/{operario_id}

**Descripción:** Obtiene recomendaciones automáticas para un operario

**URL:**
```
GET http://localhost:8080/api/recomendaciones/OP_00045
```

**Curl:**
```bash
curl -X GET "http://localhost:8080/api/recomendaciones/OP_00045" \
  -H "accept: application/json"
```

**Response (200 OK):**
```json
{
  "operario_id": "OP_00045",
  "total_recomendaciones": 3,
  "recomendaciones": [
    {
      "tipo": "caida_progresiva",
      "titulo": "🔴 ALERTA: Fatiga Detectada",
      "severidad": "CRÍTICA",
      "descripcion": "Operario pierde 22% de velocidad durante turno",
      "recomendacion": "Ofrecer pausa preventiva en próxima hora",
      "impacto": "Prevenir pérdida de ~100 picks",
      "accionable": true,
      "accion": "trigger_pausa"
    },
    {
      "tipo": "especializacion_sku",
      "titulo": "⭐ OPORTUNIDAD: Especialización",
      "severidad": "POSITIVO",
      "descripcion": "Operario es 35% más rápido con SKU SAC-4521",
      "recomendacion": "Aumentar asignación de SAC-4521",
      "impacto": "+35% productividad = ~1.820 picks extra/mes",
      "accionable": true,
      "accion": "assign_sku",
      "sku": "SAC-4521",
      "ventaja_pct": 35.0
    },
    {
      "tipo": "recuperacion_pausa",
      "titulo": "☕ OPORTUNIDAD: Pausas Estratégicas",
      "severidad": "POSITIVO",
      "descripcion": "Post-pausa almuerzo: +28% velocidad",
      "recomendacion": "Aumentar pausas almuerzo. 2 pausas = +~250 picks/turno",
      "impacto": "2 pausas estratégicas = +250 picks/turno",
      "accionable": true,
      "accion": "schedule_pausa",
      "pausa_tipo": "almuerzo",
      "mejora_pct": 28.0
    }
  ],
  "resumen": {
    "total_picks": 5200,
    "velocidad_promedio": 24.3,
    "tasa_error_pct": 2.1
  }
}
```

**Error Response (404):**
```json
{
  "detail": "Operario no encontrado"
}
```

---

### 2. GET /api/alertas

**Descripción:** Obtiene alertas activas del último período

**URL:**
```
GET http://localhost:8080/api/alertas?dias=1
```

**Query Parameters:**
- `dias`: Número de días a buscar (default: 1)

**Curl:**
```bash
curl -X GET "http://localhost:8080/api/alertas?dias=1" \
  -H "accept: application/json"
```

**Response (200 OK):**
```json
{
  "total_alertas": 2,
  "periodo_dias": 1,
  "alertas": [
    {
      "timestamp": "2026-04-20T14:30:00",
      "operario_id": "OP_00045",
      "tipo": "tasa_error_alta",
      "severidad": "CRÍTICA",
      "mensaje": "Tasa error 6.2% (esperado: 2-3%)",
      "accion_sugerida": "Revisar con operario"
    },
    {
      "timestamp": "2026-04-20T13:15:00",
      "operario_id": "OP_00067",
      "tipo": "caida_progresiva",
      "severidad": "ALTA",
      "mensaje": "Caída 18% de velocidad",
      "accion_sugerida": "Ofrecer pausa preventiva"
    }
  ]
}
```

---

### 3. POST /api/config/guardar

**Descripción:** Guarda configuración de umbrales y alertas

**URL:**
```
POST http://localhost:8080/api/config/guardar
Content-Type: application/json
```

**Curl:**
```bash
curl -X POST "http://localhost:8080/api/config/guardar" \
  -H "Content-Type: application/json" \
  -d '{
    "caida_critica": 20,
    "caida_alta": 15,
    "caida_media": 10,
    "error_maximo": 5,
    "velocidad_minima": 28,
    "especializacion_minima": 30,
    "alertas_activas": ["caida", "error", "especialidad", "pausa", "anomalia"],
    "email_destino": "supervisor@coto.com.ar",
    "frecuencia_reporte": "diaria"
  }'
```

**Request Body:**
```json
{
  "caida_critica": 20,
  "caida_alta": 15,
  "caida_media": 10,
  "error_maximo": 5,
  "velocidad_minima": 28,
  "especializacion_minima": 30,
  "alertas_activas": ["caida", "error", "especialidad", "pausa", "anomalia"],
  "email_destino": "supervisor@coto.com.ar",
  "frecuencia_reporte": "diaria"
}
```

**Response (200 OK):**
```json
{
  "status": "success",
  "mensaje": "Configuración guardada",
  "config_guardada": {
    "caida_critica": 20,
    "caida_alta": 15,
    "caida_media": 10,
    "error_maximo": 5,
    "velocidad_minima": 28,
    "especializacion_minima": 30,
    "alertas_activas": ["caida", "error", "especialidad", "pausa", "anomalia"],
    "email_destino": "supervisor@coto.com.ar",
    "frecuencia_reporte": "diaria"
  }
}
```

---

### 4. GET /api/reportes/generar

**Descripción:** Genera reportes en múltiples formatos

**URL:**
```
GET http://localhost:8080/api/reportes/generar?formato=json&tipo=diario&incluir=all
```

**Query Parameters:**
- `formato`: json, pdf, excel (default: json)
- `tipo`: diario, semanal, mensual (default: diario)
- `incluir`: ranking, graficos, anomalias, all (default: all)

**Curl - JSON:**
```bash
curl -X GET "http://localhost:8080/api/reportes/generar?formato=json&tipo=diario" \
  -H "accept: application/json"
```

**Curl - PDF:**
```bash
curl -X GET "http://localhost:8080/api/reportes/generar?formato=pdf&tipo=diario" \
  -H "accept: application/json" \
  -o reporte.pdf
```

**Curl - Excel:**
```bash
curl -X GET "http://localhost:8080/api/reportes/generar?formato=excel&tipo=semanal" \
  -H "accept: application/json" \
  -o reporte.xlsx
```

**Response - JSON (200 OK):**
```json
{
  "fecha_generacion": "2026-04-20T16:45:30",
  "tipo": "diario",
  "periodo": "últimas 24 horas",
  "resumen": {
    "total_operarios": 10,
    "total_picks": 52000,
    "total_bultos": 125000,
    "promedio_velocidad": 24.5
  },
  "ranking": [
    {
      "rank": 1,
      "operario_id": "OP_00045",
      "picks": 5200,
      "bultos": 12500,
      "velocidad": 24.3,
      "errores": 2
    },
    {
      "rank": 2,
      "operario_id": "OP_00067",
      "picks": 5100,
      "bultos": 12200,
      "velocidad": 24.6,
      "errores": 1
    }
  ]
}
```

**Response - PDF (200 OK):**
```
[PDF binary file]
```

---

## 🎨 JavaScript API (Frontend)

### Cambiar tab
```javascript
function mostrarTab(tabName) {
  // Oculta todos los tabs
  document.querySelectorAll('[id*="tab"]').forEach(el => {
    el.style.display = 'none';
  });
  
  // Muestra el tab solicitado
  document.getElementById(tabName).style.display = 'block';
  
  // Actualiza botones activos
  document.querySelectorAll('button[data-tab]').forEach(btn => {
    btn.classList.remove('active');
  });
  event.target.classList.add('active');
}
```

### Obtener recomendaciones
```javascript
async function cargarRecomendaciones() {
  const operarioId = document.getElementById('operarioSelector').value;
  
  const response = await fetch(`/api/recomendaciones/${operarioId}`);
  const data = await response.json();
  
  // Renderizar recomendaciones
  renderizarRecomendaciones(data.recomendaciones);
}
```

### Guardar configuración
```javascript
async function guardarConfig() {
  const config = {
    caida_critica: document.getElementById('caida_critica').value,
    caida_alta: document.getElementById('caida_alta').value,
    error_maximo: document.getElementById('error_maximo').value,
    // ... más parámetros
  };
  
  const response = await fetch('/api/config/guardar', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config)
  });
  
  const result = await response.json();
  console.log(result.mensaje);
}
```

---

## 📊 Algoritmo de Recomendaciones Detallado

### Paso 1: Caída Progresiva
```
IF velocidad_final / velocidad_inicial < 0.80:
  caida_pct = ((velocidad_inicial - velocidad_final) / velocidad_inicial) * 100
  
  IF caida_pct > 20:
    → CRÍTICA "Fatiga Detectada" (trigger pausa)
  ELIF caida_pct > 15:
    → ALTA "Cansancio Moderado" (monitorear)
  ELIF caida_pct > 10:
    → MEDIA "Fatiga Progresiva" (atentos)
```

### Paso 2: Especialización SKU
```
FOR each SKU:
  velocidad_promedio_sku = AVG(tiempo_segundos) WHERE sku = X
  
best_sku = sku with highest velocidad

ventaja_pct = ((velocidad_promedio - velocidad_promedio_best_sku) / velocidad_promedio) * 100

IF ventaja_pct > 30:
  → POSITIVO "Especialización" (assign SKU)
ELIF ventaja_pct > 15:
  → INFO "Tendencia de especialidad"
```

### Paso 3: Patrón Semanal
```
velocidad_por_dia = GROUP BY EXTRACT(dow from fecha)
variacion_pct = (max(vel) - min(vel)) / avg(vel) * 100

IF variacion_pct > 15:
  → INFO "Patrón Semanal" (rebalancear carga)
ELIF variacion_pct > 10:
  → BAJA "Variación moderada por día"
```

### Paso 4: Recuperación Pausa
```
FOR each pausa:
  vel_before = AVG(tiempo_segundos) in 15min before pausa
  vel_after = AVG(tiempo_segundos) in 15min after pausa
  
  recuperacion_pct = ((vel_after - vel_before) / vel_before) * 100

mejor_pausa = pausa_tipo with highest recuperacion

IF recuperacion_pct > 20:
  → POSITIVO "Pausas Estratégicas" (aumentar pausas)
ELIF recuperacion_pct > 10:
  → INFO "Pausas moderadamente efectivas"
```

### Paso 5: Anomalía Z-Score
```
z_score = (valor - promedio) / desv_estandar

IF ABS(z_score) > 2:
  → Considerado pick anómalo

pct_anomalas = COUNT(picks anomalos) / total_picks * 100

IF pct_anomalas > 5:
  → ALERTA "Picks Anormales" (investigar)
ELIF pct_anomalas > 2:
  → INFO "Algunos picks fuera de norma"
```

---

## 🔧 Troubleshooting

### Problema: "Operario no encontrado"
**Causa:** operario_id no existe en BD
**Solución:**
1. Verificar ID con GET /api/operarios
2. Asegurar que operario tiene picks registrados
3. Verificar que no haya typo en ID

### Problema: "No hay recomendaciones"
**Causa:** Operario no cumple criterios de severidad
**Solución:**
1. Datos puede ser normales (sin problemas detectados)
2. Ajustar umbrales si es demasiado conservador
3. Más picks históricos → mejores análisis

### Problema: Alertas vacío
**Causa:** No hay alertas en período
**Solución:**
1. Cambiar `dias` a número más grande
2. Generar datos con simulador
3. Verificar que haya operarios con problemas

### Problema: POST /api/config no persiste
**Causa:** Configuración en memoria (no guarda en BD)
**Solución (próxima sesión):**
1. Crear tabla `config` en BD
2. Guardar en BD en POST
3. Leer de BD en GET

---

## 📈 Casos de Uso

### Caso 1: Supervisor revisa alertas al principio del turno
```
1. Abre http://localhost:8080/config_y_recomendaciones
2. Clickea Tab "Alertas"
3. Ve alertas del día anterior
4. Lee "Acción Sugerida" para cada una
5. Toma decisiones basadas en data
```

### Caso 2: Supervisora quiere mejorar productividad operario
```
1. Abre Dashboard Config
2. Tab "Recomendaciones"
3. Selector: OP_00045
4. Ve "OPORTUNIDAD: Especialización +35% con SKU-4521"
5. Clickea "Assign SKU"
6. Sistema asigna operario a SKU favorito
```

### Caso 3: Jefe de turno necesita reportar al gerente
```
1. Abre Dashboard Config
2. Tab "Reportes"
3. Tipo: Semanal
4. Formatos: PDF + Excel
5. Clickea "Generar Reporte"
6. Descarga ambos archivos
7. Envía por email al gerente
```

### Caso 4: Personalizar umbrales por centro
```
1. Abre Dashboard Config
2. Tab "Configuración"
3. Ajusta sliders:
   - Caída Crítica: 22% (vs default 20%)
   - Error Máximo: 6% (vs default 5%)
   - Velocidad Mín: 26 seg (vs default 28)
4. Clickea "Guardar Configuración"
5. Ahora alertas usan thresholds personalizados
```

---

## 🔐 Seguridad

### CSRF Protection
- POST /api/config requiere Content-Type: application/json
- Headers validados automáticamente por FastAPI

### SQL Injection Prevention
- Todas las queries usan parameterized statements
- aiosqlite previene inyección automáticamente

### Input Validation
- operario_id: validado contra DB
- Sliders: rango 0-100 validado por HTML
- Enums: formato, tipo, incluir validados

---

## 📚 Referencias Adicionales

- **API Docs Completo:** http://localhost:8080/docs
- **OpenAPI Schema:** http://localhost:8080/openapi.json
- **Código:** `routers/operarios.py` (líneas 695-935)
- **Frontend:** `static/config_y_recomendaciones.html` (1.100+ líneas)
- **Documentación:** `SESION_1.4_RESUMEN.md`

---

**Última actualización:** 20 de abril de 2026  
**Autor:** Claude AI (Anthropic)  
**Estado:** Listo para demostración
