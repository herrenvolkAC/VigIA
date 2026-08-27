# Informe gerencial — evolución de productividad, consolidación y acceso al premio

**Fuente:** cache local de análisis de productividad (`analisis_productividad.db`).  
**Fecha de corte:** 26/08/2026.  
**Período analizado:** enero de 2024 a julio de 2026 para tendencias completas; agosto de 2026 se excluye por estar incompleto.

## 1. Objetivo

Evaluar si la caída del pago/escala de CARGA se relaciona con una transferencia de tareas de consolidación hacia PICKING y cuantificar los cambios en productividad real, equivalencias y acceso al premio.

## 2. Hallazgo ejecutivo

La evidencia disponible desde junio de 2025 es compatible con un desplazamiento de consolidación desde CARGA hacia PICKING:

- Entre junio-septiembre y octubre-diciembre de 2025, CARGA redujo sus bultos consolidados 28% y sus equivalencias 38%.
- En el mismo período, PICKING aumentó sus bultos consolidados 37% y sus equivalencias 50%.
- La participación de PICKING sobre las equivalencias de consolidación pasó de 56% a 75%.
- El efecto no es solo de volumen: PICKING genera aproximadamente 0,40–0,44 equivalentes por bulto, mientras CARGA genera aproximadamente 0,10–0,11.

Esto respalda la hipótesis de que parte de la tarea que antes contribuía a la escala de CARGA comenzó a registrarse o realizarse en PICKING.

## 3. CARGA — evolución del acceso al premio

Comparación entre el promedio enero-junio de 2024 y enero-julio de 2026:

| Indicador | Base 2024 | Ene-jul 2026 | Variación |
|---|---:|---:|---:|
| Legajos activos | 79,5 | 67,0 | -15,7% |
| Productividad real | 55.909,5 | 53.109,9 | -5,0% |
| Equivalencia total | 101.124,9 | 88.329,5 | -12,7% |
| Equivalencia por consolidación liquidada | 28.483,0 | 21.027,3 | -26,2% |
| Conversión equivalente/real | 180,9% | 166,4% | -14,5 puntos |
| Jornadas con premio | 73,5% | 48,0% | -25,5 puntos |
| Nivel promedio | 2,30 | 1,60 | -30,6% |

La cantidad de legajos no aumentó; disminuyó. Por lo tanto, el cache no respalda una explicación basada únicamente en dilución por mayor dotación.

La caída más importante está en el acceso efectivo a la escala: bajan las jornadas con premio y el nivel promedio. La productividad real cae menos que la equivalencia total, lo que indica un deterioro adicional de la conversión.

## 4. Consolidación CARGA vs PICKING

### 4.1 Volumen y equivalencias

| Período | CARGA bultos | CARGA equiv. | PICKING bultos | PICKING equiv. |
|---|---:|---:|---:|---:|
| Jun-sep 2025 | 723.014 | 81.057,9 | 254.476 | 102.202,3 |
| Oct-dic 2025 | 518.945 | 50.616,0 | 347.767 | 153.028,9 |
| Ene-jul 2026 | 1.559.538 | 147.197,2 | 694.641 | 292.888,5 |

### 4.2 Cambios entre jun-sep y oct-dic de 2025

| Indicador | CARGA | PICKING |
|---|---:|---:|
| Bultos consolidados | -28% | +37% |
| Equivalencias | -38% | +50% |
| Participación en bultos totales | 74% → 60% | 26% → 40% |
| Participación en equivalencias totales | 44% → 25% | 56% → 75% |

El cambio es consistente con una transferencia de actividad. Para que la hipótesis quede demostrada de forma definitiva, debe verificarse la fecha en que cambió la regla de pago o la asignación de funciones en la plataforma.

## 5. Productividad de PICKING

Entre junio-septiembre de 2025 y octubre-diciembre de 2025:

- La productividad real aumentó 11%.
- Los bultos de armado/consolidación aumentaron 37%.
- Las equivalencias de consolidación aumentaron 50%.
- La equivalencia por bulto pasó de aproximadamente 0,40 a 0,44.
- El porcentaje de jornadas con premio bajó de 69,2% a 65,4%.

Esto indica que PICKING absorbió más consolidación y generó más equivalencias, aunque el aumento no fue suficiente para mejorar el acceso al premio de manera generalizada.

## 6. Hallazgo sobre el período enero 2024–mayo 2025

Después de refrescar la carga local, los campos de detalle de consolidación continúan en cero para ese período en ambas operaciones. Esto debe interpretarse como una brecha de trazabilidad, no como prueba de ausencia de consolidación.

Las explicaciones posibles son:

1. Se utilizaban otros códigos de función antes de junio de 2025.
2. La consolidación se imputaba a otra operación.
3. Cambió la forma de registrar las acciones en `PV_ETAPA_CAB`/`PV_ETAPA_DET`.
4. La equivalencia se calculaba directamente en liquidación sin detalle de etapa.

Para cerrar esta brecha se debe consultar el universo completo de códigos de `PV_ETAPA_CAB` por mes, asociarlo con las descripciones de `PV_FUNCION` y comparar contra `PV_CONSOLIDACION_TIEMPO` y `PV_CARGA_TIEMPO`.

## 7. Conclusión para RRHH y gerencia operativa

El cache local muestra una caída real de la escala de CARGA: menos jornadas con premio, menor nivel promedio y menor conversión equivalente sobre producción real. La dotación no aumentó, por lo que la dilución por cantidad de personas no explica el fenómeno.

Desde junio de 2025 aparece evidencia consistente de que PICKING comenzó a concentrar una proporción mayor de la consolidación y de las equivalencias, mientras CARGA perdió participación. La hipótesis de desplazamiento de tareas es, por lo tanto, plausible y está respaldada por los datos disponibles.

La única limitación crítica para una conclusión sindical definitiva es el período enero 2024–mayo 2025: allí no aparecen registros de consolidación con los códigos actuales. Es necesario reconstruir el catálogo histórico de funciones antes de afirmar que la consolidación no existía o que el cambio comenzó exactamente en junio de 2025.

## 8. Indicadores recomendados para el tablero

- Bultos consolidados CARGA y PICKING.
- Equivalencias de consolidación CARGA y PICKING.
- Participación porcentual de cada operación.
- Equivalencias por bulto consolidado.
- Productividad real y equivalente por operación.
- Jornadas con premio y nivel promedio de CARGA.
- Línea vertical con la fecha de cada cambio de función, regla o parametrización.
