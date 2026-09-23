# Historia del operario · Oracle

Ruta: `/historia-legajo.html` (también `/historia-legajo`). Nueva página `static/historia_operario.html`; la página anterior se conserva en disco.

La tarjeta del selector usa el módulo `historia_legajo`, restaurado en APP_MODULES. Administradores y permisos ya concedidos funcionan; no se habilita acceso masivo a usuarios sin autorización.

## Origen

Todas las consultas de la nueva página usan `/api/historia-legajo/oracle/*` y SELECT contra Oracle mediante el helper JDBC existente. No leen SQLite ni hacen importaciones, snapshots o fallback. Respuestas con Cache-Control: no-store. Máximo 367 días por consulta y tres lecturas Oracle simultáneas por proceso.

- Persona actual: PV_LEGAJO.
- Jornada histórica, turno, asistencia, horas, premio cabecera: PV_DIA_LABORAL.
- Niveles, proyección OBJETIVO_PRODUCCION_8HS, umbrales aplicados, proporcional, excedentes y descuentos: PV_LIQUIDAC_DIA_DET1.
- Real, componentes equivalentes, puntos equivalentes, real más equivalentes y productividad por hora: PV_LIQUIDAC_DIA_DET2.
- Cortes: PV_LIQUIDAC_DIA_DET3.
- Tareas y movimientos: PV_ETAPA_CAB / PV_ETAPA_DET; los movimientos se paginan de a 100.
- Catálogos: PV_GRUPO_DE_FUNCIONES_CAB, PV_GRUPO_PRODUCTIVO_CAB y PV_ESCALA_DE_PREMIOS.

## Criterios

DET1 y DET2 se devuelven por separado, sin un join entre detalles que multiplique importes o producción. La interfaz agrupa por operación + grupo productivo + unidad. Proyecciones se muestran como rango de valores registrados, nunca como suma. Nivel frecuente cuenta jornadas distintas; admite empates, nivel cero y códigos como 301 sin reinterpretarlos. No se promedian niveles.

TOTAL_DE_PUNTOS_EQUIVALENTES puede incluir la producción convertida; no se suma automáticamente a PROD_REAL. TOTAL_REAL_MAS_EQUIVALENTES se muestra tal cual (incluso cero), separado de las otras columnas. Las vigencias del catálogo se informan sin asumir que una escala actual reconstruye una liquidación histórica. El detalle diario conserva el umbral realmente registrado en DET1.

Importes ocultos inicialmente. El premio cabecera corresponde a todas las operaciones de la jornada. La diferencia de importes mostrados resta ambos totales redondeados a centavos; no se atribuye a multiplicadores ni adicionales inferidos.

## Verificación

- `python -m unittest scripts.test_historia_oracle`: fechas, cardinalidad, parámetros, paginación, errores Oracle, autenticación y ruta nueva.
- `node scripts/test_historia_operario.cjs`: unidades, nulos/ceros, niveles, agregación independiente y escape.
- Consultas Oracle vivas verificadas para dos legajos en agosto de 2026; detalle y movimientos de una jornada.
- Interacción visual revisada con una muestra anonimizada en un servidor QA separado; producción conserva autenticación.

## Nivel medio mensual por varias operaciones

El gráfico independiente permite seleccionar varias series, separadas por operación, grupo productivo y unidad. Cada serie mantiene su referencia ordinal durante todo el rango consultado: se ordena el catálogo completo por umbral inferior, incluyendo códigos como 301/302/303. Si los umbrales de un mismo código varían pero conservan un orden inequívoco, se mantiene esa posición. Si los intervalos de orden se superponen o hay menos de dos niveles, no se publica un índice para esa escala. La correspondencia código → posición está visible en la explicación.

Cada fecha contribuye una sola vez a cada serie. Registros de un mismo nivel no duplican días; distintos niveles dentro del día se ponderan por TIEMPO_DURANTE_PH_EN_SEGUNDOS y se excluye la jornada si falta tiempo comparable. Se deduplican IDs de liquidación, se excluyen ausencias y niveles desconocidos. El cero fuera del catálogo solo se admite con producción positiva, acceso NO y proyección conocida por debajo del primer umbral positivo. El promedio mensual es la suma de valores diarios dividida por jornadas válidas.

Los meses sin datos no tienen punto y cortan la línea. Se informa el denominador, exclusiones, mes parcial, muestra menor a cinco jornadas y cambios observados de umbral para un mismo código. El cambio detectado no se presenta como fecha exacta de vigencia histórica. Un clic permite ver las jornadas y filtrar el detalle inferior. La selección múltiple no cambia al usar el filtro de operación individual.

No se muestra el nombre del proveedor de la base de datos en encabezados, mensajes, ayudas, errores o popups de esta pantalla. Las rutas internas y consultas conservan sus nombres técnicos.

Prueba adicional: `node scripts/test_historia_niveles.cjs`. Contraste de cálculo con tres meses de datos reales y verificación visual con Carga/Carreteo sintéticos, incluyendo un mes vacío y selección independiente.
