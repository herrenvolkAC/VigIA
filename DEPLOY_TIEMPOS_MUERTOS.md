# VigIA - prueba Tiempos muertos y TNC

## URL para usuarios

En la PC/servidor donde corre VigIA:

```text
http://localhost:9999/tiempos-muertos
```

Desde otra PC de la red:

```text
http://IP_DEL_SERVIDOR:9999/tiempos-muertos
```

Esta URL abre solo el modulo de prueba de Tiempos muertos y TNC. No muestra el resto de solapas de productividad.

## Arranque manual

```powershell
cd C:\Ingenieria\VigIA
python main.py
```

## Tarea programada recomendada

Crear una tarea de Windows con:

- Trigger: al iniciar el equipo.
- Ejecutar aunque el usuario no haya iniciado sesion.
- Ejecutar con privilegios elevados.
- Programa:

```text
python
```

- Argumentos:

```text
main.py
```

- Iniciar en:

```text
C:\Ingenieria\VigIA
```

## Firewall

Si se accede desde otras PCs, habilitar el puerto 9999:

```powershell
New-NetFirewallRule -DisplayName "VigIA 9999" -Direction Inbound -Protocol TCP -LocalPort 9999 -Action Allow
```

## Verificacion rapida

```powershell
Invoke-WebRequest -UseBasicParsing http://localhost:9999/tiempos-muertos
```

Debe responder codigo 200.
