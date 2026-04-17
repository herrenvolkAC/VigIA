# Integración de Ollama API en VigIA v2.0

## ✅ Cambios Realizados

### 1. **Backend (`routers/ai.py`)**
- ✅ Agregada función `_call_ollama()` para llamar a Ollama API
- ✅ Agregada función `_ollama_configured()` para verificar configuración
- ✅ Actualizado `_call_ai()` para soportar proveedor "ollama"
- ✅ Actualizado endpoint `/api/providers` para incluir Ollama en la lista

### 2. **Configuración (`.env` y `.env.example`)**
- ✅ Actualizado comentario de `AI_PROVIDER` para incluir "ollama" como opción
- ✅ Agregada variable `OLLAMA_URL` = `http://130.93.103.18:11434`
- ✅ Agregada variable `OLLAMA_MODEL` = `mistral` (configurable)
- ✅ `AI_PROVIDER` configurado como `ollama` (activo por defecto)

### 3. **Startup (`main.py`)**
- ✅ Mejorado logging en lifespan para mostrar URL y modelo de Ollama

---

## 🚀 Cómo Usar

### Cambiar de Proveedor

Edita `.env` y cambia `AI_PROVIDER`:

```env
# Para usar Ollama
AI_PROVIDER=ollama

# Para usar Claude (requiere ANTHROPIC_API_KEY)
AI_PROVIDER=claude

# Para usar Azure OpenAI
AI_PROVIDER=azure
```

### Configurar Ollama

```env
OLLAMA_URL=http://130.93.103.18:11434
OLLAMA_MODEL=mistral    # O el modelo que tengas: llama2, neural-chat, etc.
```

---

## 📡 Endpoint API

### `/api/analyze` (POST)
Analiza el estado operativo y devuelve alertas.

**Request:**
```json
{
  "provider": "ollama",    // opcional, usa AI_PROVIDER del .env si no se especifica
  "context": "Estado del picking...",
  "turno_id": 1
}
```

**Response:**
```json
{
  "alerts": [
    {
      "severity": "warn",
      "title": "Retraso en picking",
      "detail": "Picking: 450/1000 (45%), objetivo 1000 para hoy",
      "action": "Llamar operarios de apoyo"
    }
  ],
  "provider_used": "ollama",
  "model_used": "mistral"
}
```

### `/api/chat` (POST)
Responde preguntas del supervisor usando contexto operativo.

**Request:**
```json
{
  "provider": "ollama",    // opcional
  "message": "¿Cuál es el estado actual del picking?",
  "history": [],
  "context": "Estado operativo..."
}
```

**Response:**
```json
{
  "reply": "El picking está al 45% (450/1000 bultos). Hay retraso respecto al plan diario.",
  "provider_used": "ollama",
  "model_used": "mistral"
}
```

### `/api/providers` (GET)
Lista los proveedores disponibles y cuál está activo.

**Response:**
```json
{
  "active": "ollama",
  "available": [
    {
      "id": "claude",
      "name": "Claude (Anthropic)",
      "configured": false
    },
    {
      "id": "azure",
      "name": "Azure OpenAI",
      "configured": false
    },
    {
      "id": "ollama",
      "name": "Ollama (Local)",
      "configured": true
    }
  ]
}
```

---

## 🔍 Verificación

### 1. Verificar que Ollama está disponible

```bash
curl http://130.93.103.18:11434/api/tags
```

Debería devolver los modelos disponibles.

### 2. Verificar que VigIA ve Ollama como configurado

```bash
curl http://localhost:8080/api/providers
```

Debería mostrar `"configured": true` para Ollama.

### 3. Probar análisis con Ollama

```bash
curl -X POST http://localhost:8080/api/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "provider": "ollama",
    "context": "Picking: 450 bultos ejecutados de 1000. Tiempo: 4 horas. Objetivo: 250/hora."
  }'
```

---

## ⚙️ Modelos Soportados en Ollama

Algunos modelos populares disponibles en Ollama:

- **mistral** (por defecto) - Rápido, buena calidad
- **llama2** - Potente, mayor contexto
- **neural-chat** - Optimizado para conversación
- **orca-mini** - Ligero, rápido
- **dolphin-mixtral** - Avanzado, mejor razonamiento

Para cambiar el modelo, actualiza `OLLAMA_MODEL` en `.env` y reinicia.

---

## 📝 Notas Importantes

1. **Sin API key necesaria**: A diferencia de Claude y Azure, Ollama no requiere API keys.
2. **Latencia**: El primer request puede ser lento (~5-10s) mientras el modelo carga. Requests subsecuentes son más rápidos.
3. **Contexto**: El servidor Ollama debe estar disponible en la URL configurada.
4. **Formato JSON**: Los prompts esperan respuestas JSON válidas (para `/api/analyze`).

---

## 🔧 Troubleshooting

### Error: "OLLAMA_URL no está configurada"
- Verifica que `.env` tiene `OLLAMA_URL=http://130.93.103.18:11434`
- Reinicia el servidor FastAPI

### Error: Connection refused
- Verifica que el servidor Ollama está corriendo en `http://130.93.103.18:11434`
- Intenta: `curl http://130.93.103.18:11434/api/tags`

### Respuesta vacía de Ollama
- El modelo podría estar descargándose. Espera unos segundos.
- Verifica que `OLLAMA_MODEL` es un modelo válido en ese servidor.

---

**Versión**: VigIA 2.0 - Ollama Integration v1.0  
**Fecha**: Abril 2026
