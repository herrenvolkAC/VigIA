# VigIA Accesos Oracle para un nuevo usuario de aplicación

Fecha del relevamiento: 20/10/2026.

## Alcance y evidencia

Se cruzaron las rutas del archivo `auditoria_vigia_2026-09-01_2026-10-20.csv` con los routers, consultas SQL, puente JDBC y schedulers del código local de VigIA. La auditoría contiene 73.931 eventos HTTP entre el 01/09/2026 y el 20/10/2026 a las 14:58:47.

Los conteos son solicitudes HTTP, incluidos fallos, no ejecuciones SQL. Los jobs internos no necesitan generar eventos HTTP. Los horarios y mecanismos siguientes están confirmados en el código local; su ejecución efectiva en producción depende de la versión desplegada, variables de entorno, disponibilidad del servidor y estado de las caches. No se consultó Oracle ni se verificaron los propietarios físicos de los objetos.

La conclusión anterior de que Pañol era la principal carga Oracle por tener más eventos debe corregirse: gran parte de su operación usa SQLite. También el listado principal de Casos es local, aunque su dashboard y las consultas de posiciones sí acceden a Oracle.

## Solicitud a IT

Crear o configurar un usuario técnico para VigIA con `CREATE SESSION` y permisos `SELECT` específicos sobre los objetos correspondientes a las funciones habilitadas. En los recorridos relevados, las operaciones sobre Oracle son de lectura; las altas, modificaciones, caches e importaciones se guardan en bases locales. No se identificó necesidad de permisos de escritura Oracle para estas funciones.

No se solicita `DBA`, `SELECT ANY TABLE` ni permisos generales de modificación. El nombre del usuario nuevo y los propietarios de los objetos deben ser definidos/resueltos por IT.

Muchas consultas utilizan nombres sin esquema. Al cambiar el usuario, los permisos por sí solos pueden no ser suficientes: IT debe conservar la resolución de esos nombres mediante sinónimos privados/públicos apropiados o una estrategia equivalente de calificación de esquema. No se encontró una configuración general de `CURRENT_SCHEMA` aplicada por el puente JDBC revisado.

Las vistas se solicitan como objetos de lectura. IT debe resolver sus dependencias bajo el propietario; no se debe conceder indiscriminadamente acceso a todas sus tablas subyacentes. Tampoco debe suponerse que nombres como `ACTIVE_EMPLOYEE` y `WF_ACTIVE_EMPLOYEE` representan el mismo objeto.

## Matriz funcional y frecuencia

| Función | Objetos Oracle referenciados | Modalidad y frecuencia | Evidencia de uso HTTP |
|---|---|---|---|
| Pañol: sincronización de stock CD | `F002ARTI`, `P505STPA`, `F209CONV` | Mixto: job diario, 07:00 por defecto, y sincronización manual. Omite carga si ya existe la del día, salvo ejecución forzada. Las pantallas operativas consultan SQLite. | 49.361 eventos del módulo; no equivalen a consultas Oracle. |
| Casos: posiciones inutilizadas y dashboard | `F005UBIA`, `F671HMIH` | A demanda. Consulta al cargar dashboard, control de ubicaciones y su exportación. | Dashboard: 838; control: 226; exportación: 50. |
| Casos: stock de posiciones del ticket | `F005UBIA`, `F605RUFL`, `P505STPA`, `F002ARTI` | A demanda, condicionado por el ticket y posiciones consultadas. Puede emitir varias consultas por ticket. | No inferir cantidad SQL a partir de aperturas. El listado `/api/casos` tuvo 4.818 solicitudes y se resuelve localmente. |
| RRHH: presencias | `T_VTADOT_ZHR_PRESENCIAS` | A demanda por fechas y legajos; fragmenta los legajos en grupos de hasta 850. | `/api/rrhh/presencias`: 236 solicitudes; el filtro de presencias, 103, no debe sumarse como consulta equivalente. |
| RRHH: actividad diaria | `T_VTADOT_ZHR_PRESENCIAS` | Job diario 07:00 por defecto; también importación manual. Puede recuperar pendientes y consultar varias fechas por día operativo. | No cuantificable desde el CSV. |
| Monitor Cargas | `F810VIAJ`, `F811TRAI`, `TR_VIAJE`, `TR_CARGAS`, `TR_PALLET`, `TR_DETALLE_DE_PALLET_NEW`, `F035EXPE`, `F080CPSA`, `F081LPSA`, `F054VLOG` | A demanda con refresco de pantalla configurable entre 1 y 120 minutos; cache de 20 segundos en memoria. La ejecución forzada puede eludir la cache. | `/api/monitor-cargas/tablero`: 794 solicitudes; no necesariamente 794 consultas. |
| Herramientas: viajes y kilómetros | `F810VIAJ`, `F810VIAJ_HIST`, `F922TRAF`, `F922TRAF_HIST`, `TR_VIAJE`, `TR_TIEMPO_DE_VIAJE`, `TR_SITIO`, `ACTIVE_EMPLOYEE` | A demanda al consultar/procesar viajes. Las marcas, feriados y registros históricos operativos son locales. | 641 eventos del módulo, que no permiten separar cada lectura Oracle de las operaciones locales. |
| Recepción: proveedores, artículos y empleados | `F041PROV`, `F002ARTI`, `F602ASEC`, `WF_ACTIVE_EMPLOYEE` | A demanda en búsquedas de catálogos. Recepciones y fotografías se guardan localmente. | Catálogos: proveedores 5; artículos 3; legajos 12 solicitudes. |
| Rendimiento Online: tablero actual | `F132HIST`, `F132HIST_HIST`, `F602ASEC`, `PV_LEGAJO`, `F002ARTI`, `VW_UBICACIONES_DIVISION` | A demanda, con filtros temporales. | Tablero: 20 solicitudes. |
| Rendimiento: histórico precalculado | `PV_DIA_LABORAL`, `PV_ETAPA_CAB`, `PV_ETAPA_CAB_HIST`, `PV_ETAPA_DET`, `PV_ETAPA_DET_HIST`, `PV_FUNCION`, `PV_GRUPO_DE_FUNCIONES_DET`, `PV_GRUPO_DE_FUNCIONES_CAB`, `PV_LEGAJO`, `PV_GRUPO_PRODUCTIVO_DET`, `PV_GRUPO_PRODUCTIVO_CAB` | Job diario 06:30 y backfill manual. Revisa hasta 62 días por defecto; las caches vigentes evitan repetir trabajo. | Análisis histórico: 51 solicitudes; backfill manual: 4. Una consulta del histórico no implica recarga Oracle. |
| Rendimiento: premios/escalas | `PV_DIA_LABORAL`, `PV_ESCALA_DE_PREMIOS`, `PV_GRUPO_DE_FUNCIONES_CAB`, `PV_GRUPO_PRODUCTIVO_CAB` | Lectura asociada a cálculo/consulta de premios. | Incluida dentro del uso de Rendimiento; sin contador SQL. |
| Daily Auto / Gestión Operativa | `F132HIST`, `F602ASEC`, `F601SECT`, `PV_LEGAJO`, `WF_ACTIVE_EMPLOYEE`, `VW_UBICACIONES_DIVISION`, `F922TRAF`, `TR_VIAJE`, `TR_CARGAS`, `TR_PALLET`, `TR_DETALLE_DE_PALLET_NEW` | Mixto: precálculo diario 07:35, ventana de ejecución de 10 minutos, y recorridos manuales de cálculo. Picking, Clark y Recepción reutilizan la fuente local precargada. | El escaso uso de la pantalla no demuestra inactividad del job. |
| TNC: resumen diario RRHH | `F957ATNC`, `F956MTNC`, `PV_FUNCION` | Job 05:55 hora Argentina. Lee maestro y días pendientes; refresca los últimos tres días vencidos. Inicio histórico 01/10/2026. Reintenta fallos a los 15 minutos. | Ejecuciones internas no contabilizadas en el CSV. |
| Plantel Óptimo | `TR_VIAJE`, `TR_CARGAS`, `TR_PALLET`, `TR_DETALLE_DE_PALLET_NEW`; adicionalmente fuentes de actividad/presencia según función: `F132HIST`, `PV_LEGAJO`, `VW_UBICACIONES_DIVISION`, `T_VTADOT_ZHR_PRESENCIAS` | A demanda para demanda operativa y actividad/presencia por legajo; persiste resultados locales. | 107 eventos del módulo; 26 solicitudes a legajos-semana. |
| OpEX / Torre de Control | `F132HIST`, `VW_UBICACIONES_DIVISION` | A demanda, con snapshots SQLite reutilizados según vigencia. | 69 eventos del módulo. |
| API de productividad Parquet | `F132HIST` | A demanda del consumidor externo. Agrega las últimas 24 horas por operación y zona. Sin job propio ni cache en el endpoint revisado. | No se estableció frecuencia de consumidores externos con este CSV. |

Las tablas `F132HIST` y `F132HIST_HIST` requieren especial atención por volumen. Una única extracción de un período amplio puede costar más que cientos de solicitudes servidas desde SQLite. No se midieron tiempos, filas leídas ni consumo Oracle en este relevamiento.

## Funciones complementarias a conservar si se habilitan

Análisis de premios utiliza, además de objetos ya listados:

- `PV_LIQUIDAC_DIA_DET1`, `PV_LIQUIDAC_DIA_DET2`.
- `PV_TIEMPOS_DE_PICKING`.
- `PV_MULTIPLICADOR_CAB`, `PV_MULTIPLICADOR_DET`.
- Etapas, funciones, grupos y escalas `PV_*` incluidos en la matriz.

Se observaron 31 solicitudes a `/api/analisis-premio-productividad/consultar-rango`. El módulo combina lecturas Oracle y caches; este número no cuantifica consultas SQL.

Historia Oracle consulta legajos, jornadas, liquidaciones, etapas y escalas, e incluye `PV_LIQUIDAC_DIA_DET3`. Su router sigue incluido en la aplicación. Debe distinguirse de Historia de actividad: desactivar el job de Historia de actividad no deshabilita automáticamente todos los endpoints de Historia Oracle.

El job de Historia de actividad está condicionado por `HISTORIA_ACTIVIDAD_ENABLED`, deshabilitado por defecto. Sus ventanas predeterminadas son 21:00–22:00 y 05:00–06:00. No debe asumirse que corre en producción solo por existir su código.

Estudio de premios consume snapshots locales. El script de importación `scripts/importar_fuentes_estudio.py` lee maestros de funciones, grupos, escalas, `PV_DIA_LABORAL` y liquidaciones 1/2 de Oracle cuando se ejecuta. No se identificó ese script como scheduler iniciado por `main.py`.

CheckList, administración de usuarios/dispositivos y la operación de Horas Extras utilizan bases locales en los recorridos revisados. Horas Extras depende de datos RRHH ya cargados. No corresponde traducir sus eventos HTTP en permisos Oracle adicionales.

## Lista consolidada de objetos para resolver con IT

La siguiente lista reúne los objetos de la matriz y las funciones complementarias descritas. Otorgar únicamente los grupos funcionales que se mantendrán habilitados. No incluye aliases/CTE del SQL.

```text
ACTIVE_EMPLOYEE
F002ARTI
F005UBIA
F035EXPE
F041PROV
F054VLOG
F080CPSA
F081LPSA
F132HIST
F132HIST_HIST
F209CONV
F601SECT
F602ASEC
F605RUFL
F671HMIH
F810VIAJ
F810VIAJ_HIST
F811TRAI
F922TRAF
F922TRAF_HIST
F956MTNC
F957ATNC
P505STPA
PV_DIA_LABORAL
PV_ESCALA_DE_PREMIOS
PV_ETAPA_CAB
PV_ETAPA_CAB_HIST
PV_ETAPA_DET
PV_ETAPA_DET_HIST
PV_FUNCION
PV_GRUPO_DE_FUNCIONES_CAB
PV_GRUPO_DE_FUNCIONES_DET
PV_GRUPO_PRODUCTIVO_CAB
PV_GRUPO_PRODUCTIVO_DET
PV_LEGAJO
PV_LIQUIDAC_DIA_DET1
PV_LIQUIDAC_DIA_DET2
PV_LIQUIDAC_DIA_DET3
PV_MULTIPLICADOR_CAB
PV_MULTIPLICADOR_DET
PV_TIEMPOS_DE_PICKING
TR_CARGAS
TR_DETALLE_DE_PALLET_NEW
TR_PALLET
TR_SITIO
TR_TIEMPO_DE_VIAJE
TR_VIAJE
T_VTADOT_ZHR_PRESENCIAS
VW_UBICACIONES_DIVISION
WF_ACTIVE_EMPLOYEE
```

El objeto `F132HIST_HIST` también aparece en consultas auxiliares históricas de ubicaciones del puente JDBC. Validar su inclusión si se mantienen esas funciones. `DUAL` se usa en consultas de parámetros y habitualmente ya es accesible; verificar su resolución estándar.

## Configuración y validación del cambio de usuario

1. IT resuelve para cada nombre el propietario, tipo de objeto (tabla/vista/sinónimo) y eventual destino remoto. Esto no se puede deducir con certeza desde SQL no calificado.
2. Configurar `CREATE SESSION` y `SELECT` por objeto. Patrón orientativo: `GRANT SELECT ON <PROPIETARIO>.<OBJETO> TO <USUARIO_APLICACION>;`. No se adjunta SQL ejecutable con propietarios inventados.
3. Mantener resolución de nombres, conectividad desde el servidor VigIA al host/puerto/servicio autorizado y credenciales fuera del informe.
4. Actualizar `PRODUCTIVE_DB_USER` y `PRODUCTIVE_DB_PASSWORD` en producción. Se usan también `PRODUCTIVE_DB_HOST`, `PRODUCTIVE_DB_PORT` (1521 por defecto), `PRODUCTIVE_DB_SERVICE_NAME`. El recorrido Python puede aceptar `PRODUCTIVE_DB_DSN`; el puente JDBC forma su URL con host/puerto/servicio.
5. Validar tanto el recorrido JDBC como el recorrido Python si está habilitado: prueba de conexión, lectura de los objetos y consultas representativas de cada módulo. No es necesario ejecutar backfills completos para comprobar permisos.
6. Confirmar versión desplegada y configuración de jobs. Pañol: `PANOL_STOCK_CD_ORACLE_SYNC_ENABLED` (por defecto 1) y `PANOL_STOCK_CD_ORACLE_SYNC_TIME`. RRHH: `RRHH_ORACLE_ACTIVITY_SYNC_ENABLED` (por defecto 0), `RRHH_ORACLE_ACTIVITY_SYNC_TIME`, `RRHH_ORACLE_ACTIVITY_BACKFILL_ENABLED`, `RRHH_ORACLE_ACTIVITY_BACKFILL_MAX_DAYS` (15), `RRHH_ORACLE_ACTIVITY_MAX_DAYS_PER_RUN` (1), `RRHH_ORACLE_ACTIVITY_RETRY_MINUTES` (15).
7. TNC solo se inicia con `VIGIA_APP_ENV` productivo y `TNC_SCHEDULER_ENABLED` habilitado. Histórico de rendimiento y Daily Auto se inician desde `main.py`; los horarios 06:30 y 07:35 están definidos en código.

No dimensionar un límite de sesiones Oracle a partir de la cantidad de usuarios web. Las solicitudes concurrentes y jobs pueden abrir conexiones simultáneas bajo la misma cuenta técnica. La auditoría HTTP no permite determinar el pico real de conexiones; corresponde medirlo en Oracle durante una ventana representativa.

## Trazabilidad del relevamiento

- `main.py`: inicialización de schedulers y routers.
- `routers/panol_insumos.py`: `QUERY_STOCK_CD_ORACLE`, `_sync_cd_stock_from_oracle`, scheduler de stock.
- `routers/casos.py`: `_control_ubicaciones_payload`, dashboard, detalle de ticket y consultas JDBC de racks.
- `scripts/OracleProductividadQuery.java`: variantes `rack_stock`, `rack_inutilizadas`, `rrhh_presencias`, `stock_cd` y SQL ejecutado mediante JDBC.
- `routers/rrhh_novedades.py`: presencias, importación de actividad y scheduler Oracle.
- `routers/monitor_cargas.py`: SQL, cache y endpoint; `static/monitor_cargas.html`: intervalo de refresco.
- `routers/herramientas.py`: consultas de viajes y kilómetros.
- `routers/recepcion.py`: catálogos Oracle.
- `routers/rendimiento_online.py`: consultas actuales e históricas y scheduler.
- `routers/productividad_analisis.py`: SQL compartido, TNC y fuentes Daily Auto.
- `routers/gestion_operativa.py`: precálculo y scheduler Daily Auto.
- `utils/tnc_scheduler.py` y `scripts/cargar_tnc_resumen.py`: carga diaria TNC.
- `routers/plantel_optimo.py`, `routers/torre_control.py`, `routers/picking_parquet.py`: funciones a demanda.
- `routers/analisis_premio_productividad.py`, `routers/historia_oracle.py`, `routers/historia_legajo.py`, `scripts/importar_fuentes_estudio.py`: funciones complementarias.

Este documento es una matriz de dependencias funcionales para preparar permisos, no una medición de SQL ejecutado ni una certificación del esquema productivo. Quedan explícitamente por validar en producción los propietarios/sinónimos, versión, jobs habilitados y concurrencia.
