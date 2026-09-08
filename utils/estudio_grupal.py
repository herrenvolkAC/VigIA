"""Cálculo puro del premio grupal, separado de las fuentes y de la interfaz."""
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP


def texto(value):
    return str(value or '').strip()


def importe(value):
    return float(Decimal(str(value)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP))


def inferir_turnos(jornadas):
    """Moda por días distintos. Empate: uso más reciente y luego código menor."""
    usos = defaultdict(lambda: defaultdict(set))
    for row in jornadas:
        legajo, turno, fecha = texto(row.get('LEGAJO')), texto(row.get('TURNO')), texto(row.get('FECHA'))
        if legajo and turno and fecha:
            usos[legajo][turno].add(fecha)
    resultado = {}
    for legajo, opciones in usos.items():
        cantidad = max(len(fechas) for fechas in opciones.values())
        candidatos = [turno for turno, fechas in opciones.items() if len(fechas) == cantidad]
        ultima = max(max(opciones[t]) for t in candidatos)
        finalistas = [t for t in candidatos if max(opciones[t]) == ultima]
        elegido = min(finalistas, key=lambda t: (0, int(t)) if t.isdigit() else (1, t))
        resultado[legajo] = dict(turno_probable=elegido, dias_turno=cantidad,
            total_dias=len(set().union(*opciones.values())),
            distribucion={t: len(fechas) for t, fechas in sorted(opciones.items())},
            criterio='mayoria' if len(candidatos) == 1 else 'empate_uso_reciente')
    return resultado


def calcular_grupal(personas, jornadas, produccion, parametros, operaciones, relaciones,
                    ausencias, desde, hasta, turnos_fijos):
    """Un resultado por sector/función/turno/día y un registro por legajo.

    El legajero y el turno fijo forman la nómina. PV determina asistencia;
    toda la producción del día se atribuye exclusivamente al turno madre.
    Ausencias y polivalencias se descuentan por unión, sin duplicar personas.
    La actividad WMS nunca se usa para inferir presencia.
    """
    dias = []
    cursor = datetime.strptime(desde, '%Y%m%d')
    while cursor <= datetime.strptime(hasta, '%Y%m%d'):
        dias.append(cursor.strftime('%Y%m%d'))
        cursor += timedelta(days=1)
    asistencia = defaultdict(list)
    for row in jornadas:
        legajo, fecha = texto(row['LEGAJO']), texto(row['FECHA'])
        asistencia[fecha, legajo].append(row)
    actividad = defaultdict(list)
    for row in produccion:
        # Toda la actividad del día se atribuye al turno madre del legajo.
        # No se filtra ni se agrupa por el turno de ejecución de la tarea.
        actividad[texto(row['fecha']), texto(row['legajo'])].append(row)
    nominas = defaultdict(list)
    for row in personas:
        if row.get('active'):
            nominas[texto(row['desc_sector_generico']), texto(row['desc_funcion'])].append(row)
    alias = lambda op: 'CARGA' if op == 'CARGA CAMION' else op
    relaciones = {(alias(a), alias(b)) for a, b in relaciones}
    columnas = {'PALET': 'palets', 'BULTO': 'cantidad', 'PLU': 'plus'}
    nivel_1, nivel_2, nivel_3 = [], [], []
    for par in parametros:
        if not par.get('activo'):
            continue
        sector, funcion, turno = (texto(par[k]) for k in ('sector', 'funcion_legajero', 'turno'))
        operacion = texto(par.get('operacion_medible'))
        unidad = operaciones.get(operacion, '')
        configurado = bool(operacion and unidad in columnas and par['uc_por_operario'] > 0)
        identidad = dict(sector=sector, funcion_legajero=funcion, turno=turno,
                         operacion=operacion, unidad_medida=unidad,
                         grupo_productivo_id=par.get('grupo_productivo_id'),
                         grupo_productivo=par.get('grupo_productivo', ''))
        nomina = sorted((p for p in nominas[sector, funcion]
                         if texto(turnos_fijos.get(texto(p['legajo']))) == turno), key=lambda p: texto(p['legajo']))
        resumen = dict(identidad, nomina_total=len(nomina), dias=0, operarios_activos=0, sin_registro=0, uc_computables=0,
                       target=0, dias_cumplen=0, premio_grupal_total=0, dias_pendientes=0)
        for fecha in dias:
            people = []
            for person in nomina:
                legajo = texto(person['legajo'])
                ingreso = texto(person.get('fecha_ingreso')).replace('-', '')[:8]
                baja = texto(person.get('fecha_baja')).replace('-', '')[:8]
                vigente = not ((ingreso and fecha < ingreso) or (baja and fecha >= baja))
                records = asistencia[fecha, legajo]
                aplica_grupo = vigente
                # La pertenencia depende sólo del turno madre.
                # La vigencia afecta inclusión, no visibilidad.
                selected = records
                signatures = {(texto(r.get('AUSENTE')).upper(), texto(r.get('COD_AUSENTISMO')),
                               texto(r.get('DES_AUSENTISMO'))) for r in selected}
                confirmado = len(signatures) == 1
                flag, cod, descripcion = next(iter(signatures), ('', '', ''))
                ausente = flag in {'SI', 'SÍ', '1', 'S'}
                presente = flag in {'NO', '0', 'N'} and not cod and not descripcion
                confirmado = confirmado and (ausente or presente)
                permitida = ausente and bool(ausencias.get(cod, ausencias.get(descripcion, False)))
                acts = actividad[fecha, legajo]
                ops = {alias(texto(r['desc_funcion'])) for r in acts}
                # La operación madre viene del parámetro del grupo. Puede haber
                # polivalencia aun si ese día sólo trabajó en la otra operación.
                madre = alias(operacion)
                polivalente = any(a == madre and b in ops and a != b for a, b in relaciones)
                producida = sum(Decimal(str(r.get(columnas.get(unidad, ''), 0) or 0))
                               for r in acts if texto(r['desc_funcion']) == operacion)
                computable = producida if aplica_grupo and confirmado and presente and not polivalente else Decimal(0)
                sin_registro = not records and not acts
                motivo = ('Fuera de vigencia' if not vigente else
                          'Sin asistencia ni actividad' if sin_registro else
                          'Asistencia sin confirmar' if not confirmado else
                          'Ausente permitido' if permitida else 'Polivalencia' if polivalente else
                          'Ausente no permitido: integra meta, no cobra' if ausente else 'Incluido')
                people.append(dict(identidad, fecha=fecha, legajo=legajo, nombre=person.get('nombre', ''),
                    turno_fijo=turno,
                    asistencia='Ausente' if confirmado and ausente else 'Presente' if confirmado else 'Sin registro' if not records else 'Sin confirmar',
                    tiene_actividad=bool(acts), sin_registro=sin_registro, vigente=vigente,
                    aplica_grupo=aplica_grupo, motivo_inclusion=motivo,
                    ausencia=descripcion or cod, cod_ausentismo=cod,
                    ausencia_permitida=permitida, es_polivalencia=polivalente,
                    integra_meta=aplica_grupo and not permitida and not polivalente,
                    uc_brutas=float(producida), uc_computables=float(computable),
                    beneficiario=aplica_grupo and confirmado and presente, datos_completos=confirmado,
                    pendiente_calculo=aplica_grupo and not confirmado))
            base = sum(p['integra_meta'] for p in people)
            target_decimal = Decimal(base) * Decimal(str(par['uc_por_operario'])) * (1 - Decimal(str(par['factor_ausentismo'])) / 100)
            unidades_decimal = sum((Decimal(str(p['uc_computables'])) for p in people), Decimal(0))
            target, unidades = float(target_decimal), float(unidades_decimal)
            pending = sum(p['pendiente_calculo'] for p in people)
            evaluable = configurado and not pending and bool(people)
            cumple = evaluable and unidades_decimal > target_decimal
            pago = importe(par['premio_grupal']) if cumple else 0
            for person in people:
                person['cobra'] = cumple and person['beneficiario']
                person['premio_grupal'] = pago if person['cobra'] else 0
            estado = ('Falta operación medible u objetivo' if not configurado else
                      'Asistencia pendiente' if pending else
                      'Sin nómina activa' if not people else 'Supera la meta' if cumple else 'No supera la meta')
            day = dict(identidad, fecha=fecha, nomina_total=len(people),
                       activos=sum(p['aplica_grupo'] for p in people), operarios_activos=sum(p['aplica_grupo'] for p in people),
                       fuera_vigencia=sum(not p['vigente'] for p in people), sin_registro=sum(p['sin_registro'] for p in people),
                       presentes=sum(p['aplica_grupo'] and p['asistencia'] == 'Presente' for p in people),
                       ausentes_permitidos=sum(p['aplica_grupo'] and p['asistencia'] == 'Ausente' and p['ausencia_permitida'] for p in people),
                       ausentes_no_permitidos=sum(p['aplica_grupo'] and p['asistencia'] == 'Ausente' and not p['ausencia_permitida'] for p in people),
                       polivalentes=sum(p['aplica_grupo'] and p['es_polivalencia'] for p in people), nomina_computable=base,
                       beneficiarios=sum(p['beneficiario'] for p in people), pendientes=pending,
                       factor_ausentismo=par['factor_ausentismo'], target=target,
                       uc_computables=unidades, cumple=cumple, evaluable=evaluable,
                       parametro_configurado=configurado, estado=estado, premio_grupal=pago,
                       premio_grupal_total=importe(sum(Decimal(str(p['premio_grupal'])) for p in people)))
            nivel_2.append(day)
            nivel_3.extend(people)
            resumen['dias'] += 1
            resumen['operarios_activos'] += day['activos']
            resumen['sin_registro'] += day['sin_registro']
            resumen['uc_computables'] += unidades
            resumen['target'] += target
            resumen['dias_cumplen'] += int(cumple)
            resumen['dias_pendientes'] += int(not evaluable)
            resumen['premio_grupal_total'] += day['premio_grupal_total']
        resumen['premio_grupal_total'] = importe(resumen['premio_grupal_total'])
        resumen['cumplimiento'] = round(resumen['uc_computables'] / resumen['target'] * 100, 2) if resumen['target'] else 0
        nivel_1.append(resumen)
    grupos = {(texto(p['sector']), texto(p['funcion_legajero'])) for p in parametros if p.get('activo')}
    sin_turno = [dict(legajo=texto(p['legajo']), nombre=p.get('nombre', ''),
                     sector=texto(p['desc_sector_generico']), funcion_legajero=texto(p['desc_funcion']))
                 for p in personas if p.get('active') and not texto(turnos_fijos.get(texto(p['legajo'])))
                 and (texto(p['desc_sector_generico']), texto(p['desc_funcion'])) in grupos]
    return dict(nivel_1=nivel_1, nivel_2=nivel_2, nivel_3=nivel_3, total_filas=len(nivel_3), sin_turno=sin_turno)
