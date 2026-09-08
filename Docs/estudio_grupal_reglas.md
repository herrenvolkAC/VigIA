# Premio grupal diario — implementación del 8 de septiembre de 2026

## Regla acordada

Por sector, función del legajero, turno y fecha:

1. Plantel fijo: activos del sector/función cuyo turno de escenario guardado coincide con el parámetro. La misma lista aparece todos los días, con o sin asistencia/actividad. El cálculo y las grillas usan únicamente el turno madre. El agrupado cuenta personas únicas, no jornadas.
2. Base de la meta: activos del plantel fijo que están vigentes ese día, menos la **unión** de ausentes permitidos y polivalentes. Un mismo legajo se descuenta una sola vez. El ausente no permitido integra la base.
3. Meta: base × objetivo por operario × (1 − factor de ausentismo / 100). El factor se aplica después de los descuentos reales.
4. Producción computable: exclusivamente la operación medible asignada, de presentes no polivalentes. La unidad viene de su clasificación: PALET usa `palets`, BULTO usa `cantidad`, PLU usa `plus`.
5. La producción debe ser **estrictamente mayor** que la meta. Igualar no habilita el premio. La comparación no redondea previamente la producción.
6. Cuando se supera, cobran todos los presentes, incluidos polivalentes y presentes sin producción. Ningún ausente cobra. El premio configurado es por beneficiario; el total diario suma sus importes, redondeados a centavos HALF_UP.

Las relaciones del mapa de polivalencias son direccionales: la operación medible es la madre y la actividad en una operación adicional habilitada determina polivalencia. No es necesario haber producido también en la madre ese día. Se conserva el alias CARGA CAMION → CARGA del mapa existente.

## Fuentes y cobertura

- Nómina y sector/función: `datos/vigia.db`, `rrhh_personas`, `active=1`, con fecha de ingreso y baja evaluadas sólo para la inclusión diaria; no para recortar la nómina visible.
- Asistencia y turno: último snapshot local de `oracle.PV_DIA_LABORAL` en `lab_fuente_registro`; se usa la marca `AUSENTE`, no la existencia de producción. Se incluyen también jornadas sin actividad.
- Producción: `lab_cache_agrupado`, por fecha, legajo y operación. El cálculo ya no depende de `lab_cache_grupal`, cuya antigua carga podía perder la ausencia de personas sin producción.
- Tipos permitidos: `lab_ausencia_config`. Se incorporan códigos del snapshot y se conservan las elecciones anteriores hechas por descripción.

El legajero es el **actual**: no reconstruye transferencias históricas de sector/función. La pantalla informa esta limitación. No se conecta a Oracle ni realiza liquidaciones.

La asistencia ausente o contradictoria sigue quedando pendiente. La simulación no calcula diferencias contra el turno diario. Una fecha fuera de vigencia tampoco borra la fila; sólo excluye de meta y pago. Si faltan asistencia y actividad se señala **Sin asistencia ni actividad**.

En cada día se concilia: plantel fijo = activos vigentes + fuera de vigencia. Los legajos sin turno fijo aparecen en una lista separada de pendientes; no se duplican entre planteles.

## Turno más probable y tabla interna

`lab_turno_fijo_legajo` guarda una fila por legajo activo, con turno fijo, probable, días de uso, distribución por turno, snapshot de origen y modo automático/manual.

- Se usa el snapshot local completo de PV_DIA_LABORAL, sin recortarlo por los filtros de consulta.
- Cada combinación fecha/turno cuenta una vez, aunque la fuente tenga duplicados.
- Se elige el turno usado más días. Empate: uso más reciente; si persiste, código menor.
- La primera carga se conserva mediante INSERT OR IGNORE. Nuevas consultas, filtros o cambios de snapshot no reescriben asignaciones guardadas.
- Sin historial se guarda vacío, con criterio `sin_historial`; no se inventa turno.
- En **Parámetros grupales → Turnos fijos por legajo para escenarios** se puede buscar y modificar el turno. Se conserva el probable original y se marca `origen=manual`. Vacío permite dejarlo sin asignar.
- El cálculo usa exclusivamente el turno fijo, denominado **turno madre**, para limitar el plantel. Toda la actividad de un legajo en la fecha, incluso realizada en otros turnos, se atribuye una sola vez al turno madre. El detalle muestra sólo turno madre; se eliminaron las columnas y métricas de comparación con el turno diario. Se mantienen las reglas de operación medible, ausencias y polivalencias.
- La lista **Legajos sin turno fijo** permite encontrar pendientes de los sectores/funciones configurados y asignarlos desde Parámetros grupales.

Carga inicial real: 1.366 activos; 309 con turno 1, 316 con turno 2, 137 con turno 3 y 604 sin historial. El grupo configurado del turno 1 queda con 16 legajos, constantes durante agosto.

## Parámetros y activación

El grupo productivo es **opcional**. `lab_parametro_grupal.grupo_productivo_id` es un ID nullable del catálogo local `PV_GRUPO_PRODUCTIVO_CAB`; no se toma de la tabla de equivalencias de divisiones. La opción **Sin grupo productivo** guarda NULL y no bloquea el cálculo. Un ID informado se valida contra el catálogo. Omitir el campo en una actualización conserva la asociación; enviar NULL o vacío la quita.

La asociación se muestra en Parámetros grupales y en el agrupado. Los tres niveles de la respuesta llevan `grupo_productivo_id` y `grupo_productivo` para su futura agrupación en Premios Totales. La selección no modifica plantel, objetivo, operación ni importe del premio.

Se asoció el parámetro `CD-SECOS - ZONA 1 / CARGADOR DE SECOS / turno 1 / CARGA CAMION` al grupo **19 — AREA SECOS Y NO ALIMENTOS**. Es diferente del grupo 21 — SECOS + NOA. El recálculo de agosto conserva $4.450.000 de premio grupal simulado. La suma futura en Premios Totales deberá usar la operación de premios equivalente (CARGA) y el grupo elegido, preservando también los casos sin grupo.

`lab_parametro_grupal` incorpora `operacion_medible TEXT NOT NULL DEFAULT ''` mediante una migración idempotente. Conserva la clave sector/función/turno y los valores existentes. No asigna operaciones automáticamente.

Después de reiniciar VigIA y recargar la página, elegir una operación medible en cada fila de Parámetros grupales y guardar. La operación debe estar clasificada como medible y tener unidad PALET, BULTO o PLU en Parámetros. Objetivo > 0, factor entre 0 y 100, premio ≥ 0.

Los tres niveles sólo muestran parámetros activos. Los que no tienen operación válida conservan su nómina visible, con cálculo pendiente. El detalle muestra asistencia, ausencia y permiso, polivalencia, inclusión en la meta, producción, habilitación para cobrar, resultado e importe individual. Los filtros de fecha están disponibles dentro del cálculo grupal.

Este desarrollo modifica el simulador de Cálculo grupal diario. La solapa Premios Totales conserva su lógica anterior: su campo grupal nuevo no se alimenta todavía de este cálculo.

## Validación

`venv/Scripts/python.exe scripts/test_estudio_grupal.py`

Prueba nómina completa, descuentos superpuestos, ausentes no permitidos en la meta, pago a polivalentes presentes y presentes sin producción, igualdad y fracciones en el umbral, asistencia ausente/contradictoria, turnos, unidades, migración, guardado y validación de parámetros. Usa bases temporales. Incluye moda por días distintos, desempates, persistencia ante nueva evidencia, edición manual, falta de historial y planteles constantes al variar fechas y turnos diarios.

También se verificaron en navegador la navegación grupo → día → legajo y el guardado seguido de recálculo con datos ficticios. El snapshot real se consultó con los parámetros existentes pendientes de operación, conservando sus valores.
