# Informe ejecutivo — impacto del pago individual nuevo

## Alcance

- Período: 1 al 31 de julio de 2026.
- Universo: 332 legajos de Picking.
- Comparación: pago actual contra pago individual nuevo.
- Excluidos: pago grupal, adicionales grupales e incentivos adicionales.
- Fuente actual: cache de pago real Picking v10, con TNC y errores.
- Fuente nueva: cache de evaluación sectorial v6.

## Resultado general

| Indicador | Resultado |
|---|---:|
| Pago actual total | $50.893.571 |
| Pago individual nuevo total | $37.774.883 |
| Diferencia total | -$13.118.689 (-25,8%) |
| Legajos con pago actual positivo | 252 |
| Legajos que cobran menos | 168 (66,7% de los que tenían pago actual) |
| Legajos que cobran más | 84 (33,3%) |
| Legajos con pago actual $0 y nuevo positivo | 47 |

## Patrón 1 — el impacto está concentrado en determinadas escalas y sectores

El sector B1 concentra la mayor pérdida monetaria por volumen: 149 legajos con pago actual positivo, una reducción promedio del 22,0% y una pérdida de $7,86 millones.

El sector AM presenta la mayor señal de inequidad relativa: 15 de 16 legajos pierden, con una reducción del 62,6% y una pérdida de $2,73 millones. Su ritmo promedio es cercano a 94 bultos/hora, mientras que el pago actual los ubica en niveles diarios considerablemente superiores.

Otros casos fuertes:

- PI: -62,4% promedio.
- N1: -57,6% promedio.
- VA: -52,5% promedio.
- F1: -19,2% promedio, pero con $0,89 millones de pérdida por volumen.

La lectura para dirección es que no existe una merma uniforme: el nuevo método afecta especialmente a sectores cuya escala actual paga bien el nivel diario o las equivalencias, pero cuyo ritmo horario queda en niveles nuevos bajos.

## Patrón 2 — las jornadas con multiplicador 2 son el principal amplificador

En el cache actual hay 121 registros diarios con multiplicador 2, correspondientes a 121 legajos. En esos registros:

- Pago actual: $4,94 millones.
- Pago nuevo: $1,47 millones.
- Diferencia: -70,2%.

En registros sin multiplicador 2, la diferencia es -24,2%. Por lo tanto, el multiplicador 2 explica una parte muy relevante de las pérdidas fuertes: el nuevo cálculo individual no conserva ese efecto de duplicación del pago diario.

## Patrón 3 — cuanto más alto es el nivel actual, mayor es la probabilidad de merma

Entre legajos con pago actual positivo:

- Nivel actual promedio entre 3 y 4: -30,5%.
- Nivel actual promedio entre 4 y 5: -36,2%.
- Nivel actual promedio entre 5 y 6: -41,0%.

Esto muestra que el nuevo método no está simplemente pagando “un poco menos” por la misma escala. Está cambiando la unidad de comparación: el esquema actual premia niveles diarios y equivalencias acumuladas; el nuevo aplica una escala horaria por sector.

## Patrón 4 — bultos por hora: la zona de mayor riesgo está entre 90 y 110

La merma no crece de forma lineal con el ritmo. La zona más sensible es:

- 90–100 bultos/hora: -34,3% total.
- 100–110 bultos/hora: -41,1% total.
- 160–180 bultos/hora: -38,7% total.

Esto sugiere saltos de escala: determinados ritmos quedan por debajo de cortes horarios del nuevo modelo, aunque en el modelo actual alcanzaban una remuneración diaria alta por equivalencias, nivel o multiplicador.

## Patrón 5 — TNC y errores no explican la merma principal

Las penalizaciones acumuladas del universo son aproximadamente $100.922:

- TNC: $65.966.
- Errores: $34.956.

Representan cerca del 0,2% del pago actual total. Pueden explicar casos puntuales, pero no la pérdida general de $13,12 millones. No sería correcto presentar la merma como consecuencia de calidad.

## Casos concretos para exponer

| Legajo | Sector | Actual | Nuevo individual | Diferencia | Señal principal |
|---|---|---:|---:|---:|---|
| 203637 | B1 | $913.668 | $465.140 | -49,1% | 28 días, 223 horas, nivel actual medio 6,18; tuvo multiplicador 2 |
| 207397 | VA | $560.469 | $136.026 | -75,7% | 24 días, 206 horas, 100,7 bultos/hora; nivel actual 5,17 vs nuevo 2,09 |
| 206693 | AM | $540.398 | $154.066 | -71,5% | 25 días, 205 horas, 100,6 bultos/hora; sector AM concentra merma relativa |
| 206101 | PI | $400.656 | $108.720 | -72,9% | 24 días, 188 horas, 100,9 bultos/hora; nivel actual 4,63 vs nuevo 1,88 |
| 735249 | B1 | $3.404 | $73.649 | +2.063,6% | Caso inverso: base actual muy baja; el porcentaje no debe interpretarse sin el monto absoluto |

## Conclusión para dirección

La evidencia indica que el nuevo pago individual genera una transferencia importante desde trabajadores que hoy cobran por niveles diarios altos, equivalencias y multiplicadores hacia trabajadores con baja base actual pero actividad suficiente para la nueva escala horaria.

La causa principal a revisar no es el desempeño individual ni la calidad: es la compatibilidad entre ambas unidades de pago. Antes de reemplazar el esquema actual, deberían revisarse específicamente:

1. La continuidad del multiplicador 2 o su equivalente dentro del nuevo cálculo.
2. Las escalas de AM, PI, N1 y VA, donde la brecha relativa es muy alta.
3. Los cortes horarios entre 90 y 110 bultos/hora.
4. La relación entre equivalencias/metros del modelo actual y bultos/hora del nuevo.

El pago grupal puede compensar parte de la diferencia, pero este informe demuestra que, sin esa compensación, la merma individual está concentrada y es previsible en sectores y perfiles concretos.
