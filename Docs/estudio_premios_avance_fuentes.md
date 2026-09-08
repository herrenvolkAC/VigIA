# Estudio de premios — fuentes importadas

Snapshot: `estudio_20260907`. Destino: `datos/laboratorio_premios.db`.

## Pago actual en pantalla

Fuente confirmada por el usuario: Productividad/Oracle, no recibo de sueldo.
La carga manual `venv\Scripts\python.exe scripts/cache_pagos_actuales_estudio.py`
materializa el snapshot ya importado; no abre conexión Oracle. Es transaccional
e idempotente por snapshot. No se ejecuta desde la pantalla ni al iniciar el servidor.

- `lab_pago_actual_dia`: 23.441 jornadas, 791 legajos. Total de `PREMIO` de cabecera.
- `lab_pago_actual_operacion`: 43.786 filas DET1, conservando IDs, importes
  originales y campos de producción, tiempo, nivel, proporcional y excedente.
- `lab_pago_actual_meta`: captura, cobertura y controles del lote.
- Importes de presentación en centavos, redondeados HALF_UP por jornada/registro.
  Total diario acumulado: $113.936.256,46; detalle acumulado: $111.036.888,31.
  Se conservan los JSON originales con toda su precisión. Con este redondeo hay
  650 días/legajo cuya diferencia supera un centavo (el control original sin
  redondear informado más abajo cuenta 647).

Los endpoints `pagos-actuales` y `pagos-actuales/detalle` leen exclusivamente esta
cache. La pantalla muestra total actual y simulación parcial Carga/Traslados en
legajo y día; el nivel 3 separa Simulación de Pago actual Oracle. Las diferencias
cabecera/detalle se muestran como diferencias por conciliar, no como operaciones
inventadas. El total actual incluye todas las operaciones del legajo; los filtros
de función/grupo afectan sólo a la simulación, lo que se informa en pantalla.
Sin esos filtros se incluyen también los legajos presentes sólo en Oracle.

## Primera etapa completada

Importación manual usando la conexión Oracle de VigIA, con SELECT y commit por lote.
Los datos originales se conservan en `lab_fuente_registro` como JSON, con ordinal
para preservar filas repetidas. `lab_fuente_lote` registra consulta, segmento,
fecha de captura, filas y SHA-256. Repetir el comando con el mismo snapshot omite
lotes ya confirmados. No hay disparador de importación en pantalla ni al iniciar.

| Fuente | Filas |
|---|---:|
| Oracle: escalas de premios | 132 |
| Oracle: catálogo de funciones | 293 |
| Oracle: grupos de funciones | 71 |
| Oracle: relaciones función/grupo | 292 |
| Oracle: grupos productivos | 5 |
| Oracle: relaciones de grupos productivos | 75 |
| Análisis anterior: escalas base Picking | 22 |
| Análisis anterior: configuración sectorial Picking | 62 |
| Análisis anterior: tramos horarios sectoriales | 448 |
| Agosto: días laborales | 23.441 |
| Agosto: liquidación DET1 | 43.786 |
| Agosto: producción/equivalencias DET2 | 43.786 |

Liquidaciones: 31 lotes por tabla, 791 legajos. Sin IDs duplicados en cabecera
y DET1 ni referencias DET1 sin cabecera dentro del snapshot.

## Hallazgos para resolver antes del modelo nuevo

- Las escalas capturadas son las disponibles actualmente en Oracle. Su aplicación
  a agosto requiere validar vigencias; no se consideran automáticamente históricas.
- 58 grupos tienen registros de escala. Tener una fila de escala no alcanza para
  clasificar automáticamente una función como medible; revisar premios, unidades
  y relaciones. Las clasificaciones manuales existentes se conservan.
- DET1 liquida por grupo de funciones. La atribución a funciones de etapa necesita
  el mapa importado y control de relaciones múltiples.
- Premio de cabecera: 113.936.251,823. Suma DET1: 111.036.886,00648750755.
  Hay 647 jornadas con diferencias mayores a 0,01. No se fuerza la igualdad ni se
  interpreta todavía la diferencia como error o adicional específico.
- El universo liquidado (791 legajos) es distinto del detalle WMS de agosto
  previamente informado (684): deben identificarse los casos fuera del cruce.
- DET2 se conserva separado de DET1; no unir ambos sin comprobar cardinalidad,
  porque podría multiplicar pagos.

## Próximas etapas

1. Conciliar cabecera/DET1 y cobertura contra las etapas WMS.
2. Publicar pagos actuales por fecha, legajo y grupo, con indicadores de casos pendientes.
3. Proponer asociación de funciones y sectores a escalas; revisar dificultad
   fácil/media/difícil sin confundir categorías de sectores con tramos de pago.
4. Definir base temporal y calcular individual con explicación por registro.
5. Definir criterios y adicional de polivalencia.
6. Reconstruir plantel y turno históricos; parametrizar meta y ausencia permitida.
7. Calcular grupal y comparar individual + polivalencia + grupal contra el actual.

Verificación reproducible: `python scripts/validar_fuentes_estudio.py`.
La solapa existente de escalas consulta ahora el snapshot local importado
(132 filas, 58 operaciones), sin consulta Oracle al abrirla.
