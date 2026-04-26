"""
VigIA v2.0 · Analisis de productividad desde BD productiva.

Consulta movimientos de Picking bajo demanda y genera:
- resumen interno agregado por operario
- productividad por zona
- comparativas historicas sobre vigia.db
- lectura IA cacheada sobre el resumen agregado
"""
import asyncio
import hashlib
import json
import logging
import math
import os
import subprocess
import statistics
import unicodedata
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import aiosqlite
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from db.schema import DB_PATH
from routers.ai import _call_ai, _extract_json

logger = logging.getLogger("vigia.productividad_analisis")
router = APIRouter(prefix="/api/productividad", tags=["productividad-analisis"])
BASE_DIR = Path(__file__).parent.parent
JAVA_HELPER_SRC = BASE_DIR / "scripts" / "OracleProductividadQuery.java"
JAVA_BUILD_DIR = BASE_DIR / "scripts" / "java_build"
AI_PROMPT_VERSION = "productividad-v2"
DEFAULT_PRODUCTIVIDAD_ONLINE_OPERACIONES = [
    "PICKING",
    "GUARADO PALETS ENTRADA",
    "EXTRACCION TRASPASOS",
    "AJUSTE EN HCO. DE PICKING (X)",
    "AJUSTE EN HCO. DE PICKING (-)",
    "AJUSTE EN HCO. DE PICKING (+)",
    "AJUSTE INV. -",
    "AJUSTE INV. +",
]

QUERY_PRODUCTIVIDAD = """
SELECT
    FCREAREG AS FHMovimiento,
    CTIPTRAB AS TipoTrabajo,
    CNUPALET AS NroPallet,
    QCANTIDA AS Cantidad,
    CREFEREN AS Referencia,
    CZONAORI AS ZonaOrigen,
    CUBIORIG AS UbicOrige,
    COPECREA AS Operario,
    QPESOREG AS PesoRegistrado
FROM F132HIST
WHERE FCREAREG >= TO_DATE(:fecha_desde, 'YYYY-MM-DD HH24:MI:SS')
  AND FCREAREG <= TO_DATE(:fecha_hasta, 'YYYY-MM-DD HH24:MI:SS')
  AND CDESCRIP = 'Picking'
ORDER BY FCREAREG
"""

QUERY_PLANTEL_OPERATIVO = """
SELECT
    A.FCREAREG AS FHMovimiento,
    A.COPECREA AS Operario,
    A.QCANTIDA AS Cantidad,
    A.CZONAORI AS ZonaOrigen,
    A.CNUPALET AS NroPallet,
    A.QPESOREG AS PesoRegistrado,
    SUB1.DESCDIVI AS Almacen
FROM F132HIST A
JOIN (
    SELECT DISTINCT CZONALMA, DESCDIVI
    FROM VW_UBICACIONES_DIVISION
    WHERE DESCDIVI IN ('SECTOR SECOS', 'VARIOS NO ALIMENTOS')
) SUB1
  ON SUB1.CZONALMA = A.CZONAORI
WHERE A.FCREAREG >= TO_DATE(:fecha_desde, 'YYYY-MM-DD HH24:MI:SS')
  AND A.FCREAREG <= TO_DATE(:fecha_hasta, 'YYYY-MM-DD HH24:MI:SS')
  AND A.CDESCRIP = 'Picking'
ORDER BY A.FCREAREG
"""

QUERY_PRODUCTIVIDAD_ONLINE = """
WITH base AS (
    SELECT
        A.FCREAREG,
        A.CDESCRIP,
        A.CNUPALET,
        A.QCANTIDA,
        A.QPESOREG,
        A.COPECREA,
        B.NOMBRE AS OPERARIO,
        SUB1.DESCDIVI AS ALMACEN
    FROM F132HIST A
    LEFT JOIN PV_LEGAJO B
      ON A.COPECREA = B.LEGAJO
    LEFT JOIN (
        SELECT DISTINCT CZONALMA, DESCDIVI
        FROM VW_UBICACIONES_DIVISION
    ) SUB1
      ON SUB1.CZONALMA = A.CZONAORI
    WHERE A.FCREAREG >= TO_DATE(:fecha_desde, 'YYYY-MM-DD HH24:MI:SS')
      AND A.FCREAREG <= TO_DATE(:fecha_hasta, 'YYYY-MM-DD HH24:MI:SS')
),
seq AS (
    SELECT
        b.*,
        LAG(b.FCREAREG) OVER (
            PARTITION BY b.COPECREA, b.CDESCRIP
            ORDER BY b.FCREAREG
        ) AS f_prev
    FROM base b
),
calc AS (
    SELECT
        NVL(ALMACEN, 'SIN MAPEAR') AS ALMACEN,
        COPECREA,
        OPERARIO,
        CDESCRIP,
        QCANTIDA,
        QPESOREG,
        CNUPALET,
        FCREAREG,
        CASE
            WHEN f_prev IS NULL THEN 0
            ELSE (FCREAREG - f_prev) * 86400
        END AS dur_s
    FROM seq
),
agg AS (
    SELECT
        ALMACEN,
        COPECREA,
        OPERARIO,
        UPPER(CDESCRIP) AS CDESCRIP,
        MIN(FCREAREG) AS PRIMER_MOV,
        MAX(FCREAREG) AS ULTIMO_MOV,
        ROUND((MAX(FCREAREG) - MIN(FCREAREG)) * 24 * 60, 1) AS MINUTOS_ACTIVOS,
        COUNT(*) AS LINEAS,
        SUM(QCANTIDA) AS CANTIDAD_TOTAL,
        SUM(QPESOREG) AS PESO_TOTAL,
        COUNT(DISTINCT CNUPALET) AS PALLETS_DISTINTOS,
        SUM(dur_s) AS SEG_TOTAL
    FROM calc
    GROUP BY
        ALMACEN,
        COPECREA,
        OPERARIO,
        CDESCRIP
)
SELECT
    ALMACEN,
    COPECREA,
    OPERARIO,
    CDESCRIP AS OPERACION,
    PRIMER_MOV,
    ULTIMO_MOV,
    MINUTOS_ACTIVOS,
    LINEAS,
    CANTIDAD_TOTAL,
    PESO_TOTAL,
    PALLETS_DISTINTOS,
    ROUND(SEG_TOTAL / 3600, 2) AS HS_TOTALES,
    ROUND(CANTIDAD_TOTAL / NULLIF(SEG_TOTAL / 3600, 0), 2) AS CANTIDAD_HORA,
    ROUND(PESO_TOTAL / NULLIF(SEG_TOTAL / 3600, 0), 2) AS KG_HORA,
    CASE
        WHEN ULTIMO_MOV >= SYSDATE - (10 / 1440) THEN 'ONLINE'
        ELSE 'INACTIVO'
    END AS ESTADO
FROM agg
ORDER BY
    ALMACEN,
    COPECREA,
    OPERACION
"""

QUERY_PRODUCTIVIDAD_ONLINE_DETAIL = """
SELECT
    NVL(SUB1.DESCDIVI, 'SIN MAPEAR') AS ALMACEN,
    A.COPECREA,
    B.NOMBRE AS OPERARIO,
    UPPER(A.CDESCRIP) AS OPERACION,
    A.FCREAREG AS FH_MOVIMIENTO,
    A.CZONAORI AS ZONA_ORIGEN,
    A.CUBIORIG AS UBIC_ORIGEN,
    A.CNUPALET AS NRO_PALLET,
    A.QCANTIDA AS CANTIDAD,
    A.QPESOREG AS PESO
FROM F132HIST A
LEFT JOIN PV_LEGAJO B
  ON A.COPECREA = B.LEGAJO
LEFT JOIN (
    SELECT DISTINCT CZONALMA, DESCDIVI
    FROM VW_UBICACIONES_DIVISION
) SUB1
  ON SUB1.CZONALMA = A.CZONAORI
WHERE A.FCREAREG >= TO_DATE(:fecha_desde, 'YYYY-MM-DD HH24:MI:SS')
  AND A.FCREAREG <= TO_DATE(:fecha_hasta, 'YYYY-MM-DD HH24:MI:SS')
ORDER BY A.COPECREA, A.FCREAREG
"""

QUERY_PICKING_ANALISIS_DETAIL = """
SELECT
    NVL(SUB1.DESCDIVI, 'SIN MAPEAR') AS ALMACEN,
    A.COPECREA,
    B.NOMBRE AS OPERARIO,
    A.FCREAREG AS FH_MOVIMIENTO,
    A.CZONAORI AS ZONA_ORIGEN,
    A.CUBIORIG AS UBIC_ORIGEN,
    A.CNUPALET AS NRO_PALLET,
    A.QCANTIDA AS CANTIDAD,
    A.QPESOREG AS PESO,
    A.CREFEREN AS REFERENCIA
FROM F132HIST A
LEFT JOIN PV_LEGAJO B
  ON A.COPECREA = B.LEGAJO
LEFT JOIN (
    SELECT DISTINCT CZONALMA, DESCDIVI
    FROM VW_UBICACIONES_DIVISION
) SUB1
  ON SUB1.CZONALMA = A.CZONAORI
WHERE A.FCREAREG >= TO_DATE(:fecha_desde, 'YYYY-MM-DD HH24:MI:SS')
  AND A.FCREAREG <= TO_DATE(:fecha_hasta, 'YYYY-MM-DD HH24:MI:SS')
  AND UPPER(A.CDESCRIP) = 'PICKING'
ORDER BY A.COPECREA, A.FCREAREG
"""

SYSTEM_PRODUCTIVIDAD_ANALISIS = (
    "Sos un analista operativo senior de un centro de distribucion.\n"
    "Recibis un resumen interno de productividad de operarios de picking, "
    "incluyendo productividad general, por zona y comparativas historicas.\n"
    "Tu tarea es detectar hallazgos accionables y explicar que esta pasando.\n"
    "Responde SOLO con JSON valido, sin markdown ni texto extra:\n"
    '{"resumen":"una oracion ejecutiva",'
    '"hallazgos":["hallazgo 1","hallazgo 2","hallazgo 3"],'
    '"recomendaciones":["accion 1","accion 2","accion 3"]}\n'
    "Usa solo la informacion provista. No inventes causas externas no observables. "
    "Menciona operarios solo si aparecen en el contexto."
)

SYSTEM_PICKING_ANALISIS_IA = (
    "Sos un analista operativo senior especializado en picking.\n"
    "Recibis un resumen calculado localmente sobre productividad bruta, dificultad asignada, "
    "productividad ajustada y comparaciones justas entre operarios.\n"
    "No inventes causas externas ni afirmes certezas que no se desprendan del dataset.\n"
    "Responde SOLO con JSON valido, sin markdown ni texto extra:\n"
    '{"resumen":"oracion ejecutiva",'
    '"hallazgos":["hallazgo 1","hallazgo 2","hallazgo 3"],'
    '"recomendaciones":["accion 1","accion 2","accion 3"],'
    '"aclaraciones":["aclaracion 1","aclaracion 2"]}\n'
    "Aclara cuando algo sea una estimacion del modelo base."
)

PICKING_ANALISIS_IA_PROMPT_VERSION = "picking-ia-v1"


class AnalisisIARequest(BaseModel):
    provider: str | None = None
    resumen_interno: dict[str, Any]
    force_refresh: bool = False


class PickingAnalisisIARequest(BaseModel):
    provider: str | None = None
    analisis_base: dict[str, Any]
    force_refresh: bool = False


def _parse_dt(value: str, field_name: str) -> datetime:
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"{field_name} debe tener formato YYYY-MM-DD HH:MM:SS",
        )


def _normalize_turno(turno: str) -> str:
    raw = unicodedata.normalize("NFD", (turno or "").strip().lower())
    raw = "".join(ch for ch in raw if unicodedata.category(ch) != "Mn")
    if "man" in raw:
        return "manana"
    if "tar" in raw:
        return "tarde"
    if "noc" in raw:
        return "noche"
    raise HTTPException(status_code=400, detail=f"Turno no reconocido: {turno}")


def _normalize_operacion_name(value: str) -> str:
    raw = unicodedata.normalize("NFD", (value or "").strip().upper())
    raw = "".join(ch for ch in raw if unicodedata.category(ch) != "Mn")
    return " ".join(raw.split())


def _allowed_online_operations() -> set[str]:
    raw = os.getenv("PRODUCTIVIDAD_ONLINE_OPERACIONES", "").strip()
    source = raw.split(",") if raw else DEFAULT_PRODUCTIVIDAD_ONLINE_OPERACIONES
    return {
        normalized
        for item in source
        for normalized in [_normalize_operacion_name(item)]
        if normalized
    }


def _turn_label(turno_key: str) -> str:
    return {
        "manana": "Mañana",
        "tarde": "Tarde",
        "noche": "Noche",
    }.get(turno_key, turno_key)


def _turn_range_for_date(fecha: str, turno: str) -> tuple[str, str, str]:
    try:
        base_date = datetime.strptime(fecha, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="fecha debe tener formato YYYY-MM-DD")

    turno_key = _normalize_turno(turno)
    if turno_key == "manana":
        start_dt = base_date.replace(hour=6, minute=0, second=0)
        end_dt = base_date.replace(hour=14, minute=0, second=0)
    elif turno_key == "tarde":
        start_dt = base_date.replace(hour=14, minute=0, second=0)
        end_dt = base_date.replace(hour=22, minute=0, second=0)
    else:
        start_dt = base_date.replace(hour=22, minute=0, second=0)
        end_dt = (base_date + timedelta(days=1)).replace(hour=6, minute=0, second=0)

    return (
        turno_key,
        start_dt.strftime("%Y-%m-%d %H:%M:%S"),
        end_dt.strftime("%Y-%m-%d %H:%M:%S"),
    )


def _safe_float(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _safe_str(value: Any, default: str = "Sin dato") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def _duration_hours(dt_min: datetime | None, dt_max: datetime | None) -> float:
    if not dt_min or not dt_max:
        return 0.0
    seconds = max((dt_max - dt_min).total_seconds(), 0)
    return round(seconds / 3600, 2)


def _productivity(total: float, hours: float) -> float:
    if hours <= 0:
        return 0.0
    return round(total / hours, 2)


def _rango_key(fecha_desde: str, fecha_hasta: str) -> str:
    return f"{fecha_desde}|{fecha_hasta}"


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(value, high))


def _parse_ubic_origen(value: str) -> tuple[str, int, int] | None:
    raw = _safe_str(value, "")
    if len(raw) < 5:
        return None
    pasillo = raw[:3]
    resto = raw[3:]
    if len(resto) < 2:
        return None
    try:
        nposlarg = int(resto[-1])
        chuecopa = int(resto[:-1])
    except ValueError:
        return None
    return pasillo, chuecopa, nposlarg


def _counter_top(counter: dict[str, int], default: str = "Sin dato") -> str:
    if not counter:
        return default
    return sorted(counter.items(), key=lambda item: (-item[1], item[0]))[0][0]


def _picking_cache_row_uid(
    fecha: str,
    turno_key: str,
    fh_movimiento: str,
    copecrea: str,
    ubic_origen: str,
    nro_pallet: str,
    cantidad: float,
) -> str:
    raw = "|".join([
        fecha or "",
        turno_key or "",
        fh_movimiento or "",
        copecrea or "",
        ubic_origen or "",
        nro_pallet or "",
        f"{cantidad:.4f}",
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_payload(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _productive_db_local_only_enabled() -> bool:
    return os.getenv("PRODUCTIVE_DB_LOCAL_ONLY", "0").strip().lower() in {"1", "true", "yes", "si"}


def _query_productive_db_sql(query: str, *, fecha_desde: str, fecha_hasta: str) -> list[dict[str, Any]]:
    if _productive_db_local_only_enabled():
        raise RuntimeError(
            "La BD productiva Oracle esta temporalmente bloqueada por configuracion. "
            "El sistema esta operando en modo solo local."
        )

    if os.getenv("PRODUCTIVE_DB_USE_JDBC", "1").strip().lower() in {"1", "true", "yes", "si"}:
        return _query_productive_db_via_jdbc(query, fecha_desde, fecha_hasta)

    try:
        import oracledb
    except ImportError as exc:
        raise RuntimeError(
            "Falta instalar la dependencia 'oracledb'. Agregala al entorno del servidor."
        ) from exc

    user = os.getenv("PRODUCTIVE_DB_USER", "").strip()
    password = os.getenv("PRODUCTIVE_DB_PASSWORD", "").strip()
    host = os.getenv("PRODUCTIVE_DB_HOST", "").strip()
    port = os.getenv("PRODUCTIVE_DB_PORT", "1521").strip()
    service_name = os.getenv("PRODUCTIVE_DB_SERVICE_NAME", "").strip()

    if not all([user, password, host, service_name]):
        raise RuntimeError(
            "Faltan variables de conexion a BD productiva: "
            "PRODUCTIVE_DB_USER, PRODUCTIVE_DB_PASSWORD, PRODUCTIVE_DB_HOST, "
            "PRODUCTIVE_DB_SERVICE_NAME."
        )

    dsn = os.getenv("PRODUCTIVE_DB_DSN", "").strip()
    if not dsn:
        dsn = oracledb.makedsn(host=host, port=int(port), service_name=service_name)

    client_lib_dir = os.getenv("PRODUCTIVE_DB_CLIENT_LIB_DIR", "").strip()
    if client_lib_dir:
        try:
            oracledb.init_oracle_client(lib_dir=client_lib_dir)
        except Exception as exc:
            msg = str(exc)
            if "DPI-1050" in msg:
                raise RuntimeError(
                    "El cliente Oracle configurado es demasiado viejo. "
                    "python-oracledb requiere Oracle Client 11.2 o superior para modo thick. "
                    f"Ruta actual: {client_lib_dir}"
                ) from exc
            if "init_oracle_client()" in msg and "already been initialized" in msg:
                pass
            else:
                raise RuntimeError(
                    "No se pudo inicializar el cliente Oracle en modo thick. "
                    f"Ruta configurada: {client_lib_dir}. Error: {msg}"
                ) from exc

    connection = oracledb.connect(user=user, password=password, dsn=dsn)
    try:
        cursor = connection.cursor()
        cursor.execute(
            query,
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
        )
        columns = [col[0] for col in cursor.description]
        rows = []
        for row in cursor.fetchall():
            rows.append(dict(zip(columns, row)))
        return rows
    finally:
        try:
            cursor.close()
        except Exception:
            pass
        connection.close()


def _query_productive_db(fecha_desde: str, fecha_hasta: str) -> list[dict[str, Any]]:
    return _query_productive_db_sql(
        QUERY_PRODUCTIVIDAD,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
    )


def query_productive_db_plantel(fecha_desde: str, fecha_hasta: str) -> list[dict[str, Any]]:
    return _query_productive_db_sql(
        QUERY_PLANTEL_OPERATIVO,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
    )


def query_productive_db_online(fecha_desde: str, fecha_hasta: str) -> list[dict[str, Any]]:
    return _query_productive_db_sql(
        QUERY_PRODUCTIVIDAD_ONLINE_DETAIL,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
    )


def query_productive_db_online_detail(fecha_desde: str, fecha_hasta: str) -> list[dict[str, Any]]:
    return _query_productive_db_sql(
        QUERY_PRODUCTIVIDAD_ONLINE_DETAIL,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
    )


def query_productive_db_picking_analysis_detail(fecha_desde: str, fecha_hasta: str) -> list[dict[str, Any]]:
    return _query_productive_db_sql(
        QUERY_PICKING_ANALISIS_DETAIL,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
    )


def _ensure_java_helper_compiled() -> None:
    javac_bin = os.getenv(
        "PRODUCTIVE_DB_JAVAC_BIN",
        r"C:\Program Files\Android\openjdk\jdk-21.0.8\bin\javac.exe",
    ).strip()
    if not Path(javac_bin).exists():
        raise RuntimeError(
            f"No se encontró javac para el fallback JDBC. Ruta configurada: {javac_bin}"
        )

    JAVA_BUILD_DIR.mkdir(parents=True, exist_ok=True)
    class_file = JAVA_BUILD_DIR / "OracleProductividadQuery.class"
    if class_file.exists() and class_file.stat().st_mtime >= JAVA_HELPER_SRC.stat().st_mtime:
        return

    result = subprocess.run(
        [javac_bin, "-d", str(JAVA_BUILD_DIR), str(JAVA_HELPER_SRC)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "No se pudo compilar el helper JDBC de Oracle. "
            f"STDERR: {result.stderr.strip() or result.stdout.strip()}"
        )


def _query_productive_db_via_jdbc(query: str, fecha_desde: str, fecha_hasta: str) -> list[dict[str, Any]]:
    user = os.getenv("PRODUCTIVE_DB_USER", "").strip()
    password = os.getenv("PRODUCTIVE_DB_PASSWORD", "").strip()
    host = os.getenv("PRODUCTIVE_DB_HOST", "").strip()
    port = os.getenv("PRODUCTIVE_DB_PORT", "1521").strip()
    service_name = os.getenv("PRODUCTIVE_DB_SERVICE_NAME", "").strip()
    java_bin = os.getenv(
        "PRODUCTIVE_DB_JAVA_BIN",
        r"C:\Users\207189\AppData\Local\DBeaver\jre\bin\java.exe",
    ).strip()
    ojdbc_jar = os.getenv(
        "PRODUCTIVE_DB_OJDBC_JAR",
        r"C:\Users\207189\AppData\Roaming\DBeaverData\drivers\maven\maven-central\com.oracle.database.jdbc\ojdbc11-23.2.0.0.jar",
    ).strip()

    if not all([user, host, service_name]):
        raise RuntimeError(
            "Faltan variables de conexion JDBC a BD productiva: "
            "PRODUCTIVE_DB_USER, PRODUCTIVE_DB_HOST, PRODUCTIVE_DB_SERVICE_NAME."
        )
    if not password:
        raise RuntimeError("Falta completar PRODUCTIVE_DB_PASSWORD en .env.")
    if not Path(java_bin).exists():
        raise RuntimeError(f"No se encontró Java para fallback JDBC: {java_bin}")
    if not Path(ojdbc_jar).exists():
        raise RuntimeError(f"No se encontró el driver JDBC Oracle: {ojdbc_jar}")

    _ensure_java_helper_compiled()
    jdbc_url = f"jdbc:oracle:thin:@//{host}:{port}/{service_name}"
    classpath = os.pathsep.join([str(JAVA_BUILD_DIR), ojdbc_jar])
    normalized_query = " ".join(query.upper().split())
    if (
        "PV_LEGAJO" in normalized_query
        and "VW_UBICACIONES_DIVISION" in normalized_query
        and "UPPER(A.CDESCRIP) = 'PICKING'" in normalized_query
    ):
        query_key = "picking_analysis"
    elif "PV_LEGAJO" in normalized_query and "VW_UBICACIONES_DIVISION" in normalized_query:
        query_key = "online"
    elif "VW_UBICACIONES_DIVISION" in normalized_query:
        query_key = "plantel"
    else:
        query_key = "productividad"

    result = subprocess.run(
        [
            java_bin,
            "-cp",
            classpath,
            "OracleProductividadQuery",
            jdbc_url,
            user,
            password,
            fecha_desde,
            fecha_hasta,
            query_key,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "No se pudo consultar Oracle via JDBC. "
            f"STDERR: {result.stderr.strip() or result.stdout.strip()}"
        )

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"La respuesta JDBC no fue JSON válido. Salida: {result.stdout[:300]}"
        ) from exc


def _build_internal_summary(
    rows: list[dict[str, Any]],
    fecha_desde: str,
    fecha_hasta: str,
) -> dict[str, Any]:
    movimientos = []
    por_operario: dict[str, dict[str, Any]] = {}
    por_zona_global: dict[str, dict[str, Any]] = {}
    zonas_por_operario: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)

    for raw in rows:
        fh = raw.get("FHMOVIMIENTO")
        if isinstance(fh, str) and fh:
            try:
                fh = datetime.fromisoformat(fh)
            except ValueError:
                fh = None
        operario = _safe_str(raw.get("OPERARIO"))
        zona = _safe_str(raw.get("ZONAORIGEN"))
        cantidad = _safe_float(raw.get("CANTIDAD"))
        peso = _safe_float(raw.get("PESOREGISTRADO"))
        pallet = raw.get("NROPALLET")

        movimientos.append({
            "fh_movimiento": fh.isoformat() if hasattr(fh, "isoformat") else str(fh),
            "operario": operario,
            "zona": zona,
            "cantidad": cantidad,
            "peso_registrado": peso,
            "nro_pallet": str(pallet).strip() if pallet is not None else "",
        })

        if operario not in por_operario:
            por_operario[operario] = {
                "operario": operario,
                "movimientos": 0,
                "cantidad_total": 0.0,
                "peso_total": 0.0,
                "pallets": set(),
                "primer_movimiento": fh,
                "ultimo_movimiento": fh,
            }

        op = por_operario[operario]
        op["movimientos"] += 1
        op["cantidad_total"] += cantidad
        op["peso_total"] += peso
        if pallet is not None and str(pallet).strip():
            op["pallets"].add(str(pallet).strip())
        if fh and (op["primer_movimiento"] is None or fh < op["primer_movimiento"]):
            op["primer_movimiento"] = fh
        if fh and (op["ultimo_movimiento"] is None or fh > op["ultimo_movimiento"]):
            op["ultimo_movimiento"] = fh

        if zona not in por_zona_global:
            por_zona_global[zona] = {
                "zona": zona,
                "movimientos": 0,
                "cantidad_total": 0.0,
                "peso_total": 0.0,
                "operarios": set(),
                "primer_movimiento": fh,
                "ultimo_movimiento": fh,
            }
        zg = por_zona_global[zona]
        zg["movimientos"] += 1
        zg["cantidad_total"] += cantidad
        zg["peso_total"] += peso
        zg["operarios"].add(operario)
        if fh and (zg["primer_movimiento"] is None or fh < zg["primer_movimiento"]):
            zg["primer_movimiento"] = fh
        if fh and (zg["ultimo_movimiento"] is None or fh > zg["ultimo_movimiento"]):
            zg["ultimo_movimiento"] = fh

        if zona not in zonas_por_operario[operario]:
            zonas_por_operario[operario][zona] = {
                "zona": zona,
                "movimientos": 0,
                "cantidad_total": 0.0,
                "peso_total": 0.0,
                "primer_movimiento": fh,
                "ultimo_movimiento": fh,
            }
        zo = zonas_por_operario[operario][zona]
        zo["movimientos"] += 1
        zo["cantidad_total"] += cantidad
        zo["peso_total"] += peso
        if fh and (zo["primer_movimiento"] is None or fh < zo["primer_movimiento"]):
            zo["primer_movimiento"] = fh
        if fh and (zo["ultimo_movimiento"] is None or fh > zo["ultimo_movimiento"]):
            zo["ultimo_movimiento"] = fh

    operarios = []
    for operario, info in por_operario.items():
        horas_activas = _duration_hours(info["primer_movimiento"], info["ultimo_movimiento"])
        productividad_general = _productivity(info["cantidad_total"], horas_activas)
        productividad_mov_hora = _productivity(info["movimientos"], horas_activas)
        zonas = []
        for zona, zinfo in zonas_por_operario[operario].items():
            horas_zona = _duration_hours(zinfo["primer_movimiento"], zinfo["ultimo_movimiento"])
            zonas.append({
                "zona": zona,
                "movimientos": zinfo["movimientos"],
                "cantidad_total": round(zinfo["cantidad_total"], 2),
                "peso_total": round(zinfo["peso_total"], 2),
                "horas_activas": horas_zona,
                "productividad": _productivity(zinfo["cantidad_total"], horas_zona),
            })
        zonas.sort(key=lambda item: item["productividad"], reverse=True)
        operarios.append({
            "operario": operario,
            "movimientos": info["movimientos"],
            "cantidad_total": round(info["cantidad_total"], 2),
            "peso_total": round(info["peso_total"], 2),
            "pallets_unicos": len(info["pallets"]),
            "primer_movimiento": info["primer_movimiento"].isoformat() if info["primer_movimiento"] else None,
            "ultimo_movimiento": info["ultimo_movimiento"].isoformat() if info["ultimo_movimiento"] else None,
            "horas_activas": horas_activas,
            "productividad_general": productividad_general,
            "movimientos_por_hora": productividad_mov_hora,
            "zonas": zonas,
        })

    operarios.sort(
        key=lambda item: (item["productividad_general"], item["cantidad_total"]),
        reverse=True,
    )

    productividades = [o["productividad_general"] for o in operarios if o["productividad_general"] > 0]
    promedio = round(sum(productividades) / len(productividades), 2) if productividades else 0.0

    for item in operarios:
        item["desvio_vs_promedio_pct"] = round(
            ((item["productividad_general"] - promedio) / promedio) * 100, 2
        ) if promedio > 0 else 0.0
        item["estado"] = (
            "ok" if item["productividad_general"] >= promedio else
            "warn" if item["productividad_general"] >= promedio * 0.8 else
            "bad"
        )

    zonas = []
    for zona, info in por_zona_global.items():
        horas = _duration_hours(info["primer_movimiento"], info["ultimo_movimiento"])
        zonas.append({
            "zona": zona,
            "movimientos": info["movimientos"],
            "cantidad_total": round(info["cantidad_total"], 2),
            "peso_total": round(info["peso_total"], 2),
            "operarios": len(info["operarios"]),
            "horas_activas": horas,
            "productividad": _productivity(info["cantidad_total"], horas),
        })
    zonas.sort(key=lambda item: item["productividad"], reverse=True)

    total_cantidad = round(sum(o["cantidad_total"] for o in operarios), 2)
    total_peso = round(sum(o["peso_total"] for o in operarios), 2)
    total_movimientos = len(rows)
    top_operarios = operarios[:5]
    bottom_operarios = sorted(
        operarios,
        key=lambda item: (item["productividad_general"], item["cantidad_total"]),
    )[:5]

    alertas = []
    if operarios:
        if promedio > 0:
            bajos = [o for o in operarios if o["productividad_general"] < promedio * 0.8]
            if bajos:
                alertas.append(
                    f"{len(bajos)} operarios quedaron mas de 20% por debajo del promedio de la ventana."
                )
        if zonas:
            mejor_zona = zonas[0]
            peor_zona = zonas[-1]
            if mejor_zona["zona"] != peor_zona["zona"] and peor_zona["productividad"] > 0:
                brecha = round(mejor_zona["productividad"] - peor_zona["productividad"], 2)
                alertas.append(
                    f"La zona {mejor_zona['zona']} rindio {brecha} unidades/h por encima de {peor_zona['zona']}."
                )

    return {
        "rango": {
            "fecha_desde": fecha_desde,
            "fecha_hasta": fecha_hasta,
        },
        "resumen": {
            "movimientos_total": total_movimientos,
            "operarios_total": len(operarios),
            "zonas_total": len(zonas),
            "cantidad_total": total_cantidad,
            "peso_total": total_peso,
            "productividad_promedio": promedio,
        },
        "alertas_internas": alertas,
        "top_operarios": top_operarios,
        "bottom_operarios": bottom_operarios,
        "zonas": zonas,
        "operarios": operarios,
        "muestra_movimientos": movimientos[:200],
    }


async def _get_cached_run(db: aiosqlite.Connection, fecha_desde: str, fecha_hasta: str) -> aiosqlite.Row | None:
    db.row_factory = aiosqlite.Row
    async with db.execute(
        """
        SELECT *
        FROM productividad_analisis_runs
        WHERE rango_key = ?
        LIMIT 1
        """,
        (_rango_key(fecha_desde, fecha_hasta),),
    ) as cur:
        return await cur.fetchone()


async def _save_run_details(db: aiosqlite.Connection, run_id: int, resumen: dict[str, Any]) -> None:
    await db.execute("DELETE FROM productividad_analisis_operario WHERE run_id = ?", (run_id,))
    await db.execute("DELETE FROM productividad_analisis_operario_zona WHERE run_id = ?", (run_id,))
    await db.execute("DELETE FROM productividad_analisis_zona WHERE run_id = ?", (run_id,))

    for operario in resumen.get("operarios", []):
        await db.execute(
            """
            INSERT INTO productividad_analisis_operario (
                run_id, operario, movimientos, cantidad_total, peso_total, pallets_unicos,
                horas_activas, productividad_general, movimientos_por_hora,
                desvio_vs_promedio_pct, estado
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                operario.get("operario"),
                operario.get("movimientos", 0),
                operario.get("cantidad_total", 0.0),
                operario.get("peso_total", 0.0),
                operario.get("pallets_unicos", 0),
                operario.get("horas_activas", 0.0),
                operario.get("productividad_general", 0.0),
                operario.get("movimientos_por_hora", 0.0),
                operario.get("desvio_vs_promedio_pct", 0.0),
                operario.get("estado"),
            ),
        )
        for zona in operario.get("zonas", []):
            await db.execute(
                """
                INSERT INTO productividad_analisis_operario_zona (
                    run_id, operario, zona, movimientos, cantidad_total,
                    peso_total, horas_activas, productividad
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    operario.get("operario"),
                    zona.get("zona"),
                    zona.get("movimientos", 0),
                    zona.get("cantidad_total", 0.0),
                    zona.get("peso_total", 0.0),
                    zona.get("horas_activas", 0.0),
                    zona.get("productividad", 0.0),
                ),
            )

    for zona in resumen.get("zonas", []):
        await db.execute(
            """
            INSERT INTO productividad_analisis_zona (
                run_id, zona, movimientos, cantidad_total, peso_total,
                operarios, horas_activas, productividad
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                zona.get("zona"),
                zona.get("movimientos", 0),
                zona.get("cantidad_total", 0.0),
                zona.get("peso_total", 0.0),
                zona.get("operarios", 0),
                zona.get("horas_activas", 0.0),
                zona.get("productividad", 0.0),
            ),
        )


async def _create_or_replace_run(
    db: aiosqlite.Connection,
    fecha_desde: str,
    fecha_hasta: str,
    rows_count: int,
    resumen: dict[str, Any],
) -> int:
    resumen_hash = _hash_payload(resumen)
    await db.execute(
        """
        INSERT INTO productividad_analisis_runs (
            rango_key, fecha_desde, fecha_hasta, source_rows_count,
            resumen_hash, resumen_json, oracle_cached_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ON CONFLICT(rango_key) DO UPDATE SET
            fecha_desde = excluded.fecha_desde,
            fecha_hasta = excluded.fecha_hasta,
            source_rows_count = excluded.source_rows_count,
            resumen_hash = excluded.resumen_hash,
            resumen_json = excluded.resumen_json,
            oracle_cached_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP,
            ia_provider = NULL,
            ia_model = NULL,
            ia_prompt_version = NULL,
            ia_summary_hash = NULL,
            ia_json = NULL,
            ia_generated_at = NULL
        """,
        (
            _rango_key(fecha_desde, fecha_hasta),
            fecha_desde,
            fecha_hasta,
            rows_count,
            resumen_hash,
            _canonical_json(resumen),
        ),
    )
    async with db.execute(
        "SELECT run_id FROM productividad_analisis_runs WHERE rango_key = ?",
        (_rango_key(fecha_desde, fecha_hasta),),
    ) as cur:
        row = await cur.fetchone()
    return row[0]


async def _historical_operario_stats(
    db: aiosqlite.Connection,
    run_id: int,
) -> dict[str, dict[str, float]]:
    stats = {}
    async with db.execute(
        """
        SELECT operario,
               COUNT(*) AS ventanas,
               ROUND(AVG(productividad_general), 2) AS promedio,
               ROUND(MIN(productividad_general), 2) AS minimo,
               ROUND(MAX(productividad_general), 2) AS maximo
        FROM productividad_analisis_operario
        WHERE run_id <> ?
        GROUP BY operario
        """,
        (run_id,),
    ) as cur:
        async for row in cur:
            stats[row[0]] = {
                "ventanas": row[1],
                "promedio": row[2] or 0.0,
                "minimo": row[3] or 0.0,
                "maximo": row[4] or 0.0,
            }
    return stats


async def _historical_zona_stats(
    db: aiosqlite.Connection,
    run_id: int,
) -> dict[str, dict[str, float]]:
    stats = {}
    async with db.execute(
        """
        SELECT zona,
               COUNT(*) AS ventanas,
               ROUND(AVG(productividad), 2) AS promedio,
               ROUND(MIN(productividad), 2) AS minimo,
               ROUND(MAX(productividad), 2) AS maximo
        FROM productividad_analisis_zona
        WHERE run_id <> ?
        GROUP BY zona
        """,
        (run_id,),
    ) as cur:
        async for row in cur:
            stats[row[0]] = {
                "ventanas": row[1],
                "promedio": row[2] or 0.0,
                "minimo": row[3] or 0.0,
                "maximo": row[4] or 0.0,
            }
    return stats


async def _enrich_summary_with_history(
    db: aiosqlite.Connection,
    run_id: int,
    resumen: dict[str, Any],
) -> dict[str, Any]:
    operario_stats = await _historical_operario_stats(db, run_id)
    zona_stats = await _historical_zona_stats(db, run_id)

    comparativas_operario = []
    for operario in resumen.get("operarios", []):
        hist = operario_stats.get(operario["operario"])
        if hist and hist["ventanas"] > 0:
            delta = round(operario["productividad_general"] - hist["promedio"], 2)
            delta_pct = round((delta / hist["promedio"]) * 100, 2) if hist["promedio"] > 0 else 0.0
            operario["historico"] = {
                "ventanas": hist["ventanas"],
                "promedio_productividad": hist["promedio"],
                "minimo_productividad": hist["minimo"],
                "maximo_productividad": hist["maximo"],
                "delta_vs_promedio": delta,
                "delta_vs_promedio_pct": delta_pct,
            }
            comparativas_operario.append({
                "operario": operario["operario"],
                "actual": operario["productividad_general"],
                "promedio_historico": hist["promedio"],
                "delta": delta,
                "delta_pct": delta_pct,
                "ventanas": hist["ventanas"],
            })
        else:
            operario["historico"] = None

    comparativas_zona = []
    for zona in resumen.get("zonas", []):
        hist = zona_stats.get(zona["zona"])
        if hist and hist["ventanas"] > 0:
            delta = round(zona["productividad"] - hist["promedio"], 2)
            delta_pct = round((delta / hist["promedio"]) * 100, 2) if hist["promedio"] > 0 else 0.0
            zona["historico"] = {
                "ventanas": hist["ventanas"],
                "promedio_productividad": hist["promedio"],
                "minimo_productividad": hist["minimo"],
                "maximo_productividad": hist["maximo"],
                "delta_vs_promedio": delta,
                "delta_vs_promedio_pct": delta_pct,
            }
            comparativas_zona.append({
                "zona": zona["zona"],
                "actual": zona["productividad"],
                "promedio_historico": hist["promedio"],
                "delta": delta,
                "delta_pct": delta_pct,
                "ventanas": hist["ventanas"],
            })
        else:
            zona["historico"] = None

    comparativas_operario.sort(key=lambda item: item["delta_pct"])
    comparativas_zona.sort(key=lambda item: item["delta_pct"])
    caidos = [item for item in comparativas_operario if item["delta_pct"] <= -15]
    destacados = sorted(comparativas_operario, key=lambda item: item["delta_pct"], reverse=True)[:5]
    zonas_caidas = [item for item in comparativas_zona if item["delta_pct"] <= -15]

    alertas = list(resumen.get("alertas_internas", []))
    if caidos:
        alertas.append(
            f"{len(caidos)} operarios quedaron al menos 15% por debajo de su promedio historico."
        )
    if zonas_caidas:
        alertas.append(
            f"{len(zonas_caidas)} zonas quedaron al menos 15% por debajo de su productividad historica."
        )

    resumen["alertas_internas"] = alertas
    resumen["historico"] = {
        "muestras_operario": sum(1 for item in comparativas_operario if item["ventanas"] > 0),
        "muestras_zona": sum(1 for item in comparativas_zona if item["ventanas"] > 0),
        "operarios_mas_bajos_vs_historico": caidos[:5],
        "operarios_mas_altos_vs_historico": destacados[:5],
        "zonas_mas_bajas_vs_historico": zonas_caidas[:5],
        "zonas_mas_altas_vs_historico": sorted(
            comparativas_zona, key=lambda item: item["delta_pct"], reverse=True
        )[:5],
    }
    return resumen


async def _finalize_run_summary(
    db: aiosqlite.Connection,
    run_id: int,
    resumen: dict[str, Any],
) -> dict[str, Any]:
    resumen_hash = _hash_payload(resumen)
    await db.execute(
        """
        UPDATE productividad_analisis_runs
        SET resumen_hash = ?,
            resumen_json = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE run_id = ?
        """,
        (resumen_hash, _canonical_json(resumen), run_id),
    )
    return resumen


async def _get_cached_internal_summary(
    fecha_desde: str,
    fecha_hasta: str,
) -> dict[str, Any] | None:
    async with aiosqlite.connect(DB_PATH) as db:
        row = await _get_cached_run(db, fecha_desde, fecha_hasta)
        if not row or not row["resumen_json"]:
            return None
        resumen = json.loads(row["resumen_json"])
        resumen["cache"] = {
            "interno_cache_hit": True,
            "run_id": row["run_id"],
            "oracle_cached_at": row["oracle_cached_at"],
        }
        return resumen


async def build_or_get_internal_analysis(
    fecha_desde: str,
    fecha_hasta: str,
    force_refresh: bool = False,
) -> dict[str, Any]:
    cached = await _get_cached_internal_summary(fecha_desde, fecha_hasta)
    if cached and not force_refresh:
        return cached

    if _productive_db_local_only_enabled():
        if cached:
            return cached
        raise RuntimeError(
            "Modo solo local activo: no se consulto Oracle y no existe cache local para ese rango. "
            "Probá con un rango ya cargado en vigia.db o desactivá PRODUCTIVE_DB_LOCAL_ONLY."
        )

    rows = await asyncio.to_thread(_query_productive_db, fecha_desde, fecha_hasta)
    resumen = _build_internal_summary(rows, fecha_desde, fecha_hasta)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        run_id = await _create_or_replace_run(db, fecha_desde, fecha_hasta, len(rows), resumen)
        await _save_run_details(db, run_id, resumen)
        resumen = await _enrich_summary_with_history(db, run_id, resumen)
        resumen = await _finalize_run_summary(db, run_id, resumen)
        await db.commit()

    resumen["cache"] = {
        "interno_cache_hit": False,
        "run_id": run_id,
    }
    return resumen


def _build_ai_context(resumen_interno: dict[str, Any]) -> str:
    resumen = resumen_interno.get("resumen", {})
    top = resumen_interno.get("top_operarios", [])[:5]
    bottom = resumen_interno.get("bottom_operarios", [])[:5]
    zonas = resumen_interno.get("zonas", [])[:8]
    alertas = resumen_interno.get("alertas_internas", [])
    historico = resumen_interno.get("historico", {})
    historico_bajos = historico.get("operarios_mas_bajos_vs_historico", [])[:5]
    historico_zonas = historico.get("zonas_mas_bajas_vs_historico", [])[:5]

    return "\n".join([
        "ANALISIS INTERNO DE PRODUCTIVIDAD PICKING",
        f"Rango: {resumen_interno.get('rango', {}).get('fecha_desde')} a {resumen_interno.get('rango', {}).get('fecha_hasta')}",
        "",
        "RESUMEN GENERAL",
        f"- Movimientos: {resumen.get('movimientos_total', 0)}",
        f"- Operarios: {resumen.get('operarios_total', 0)}",
        f"- Zonas: {resumen.get('zonas_total', 0)}",
        f"- Cantidad total: {resumen.get('cantidad_total', 0)}",
        f"- Peso total: {resumen.get('peso_total', 0)}",
        f"- Productividad promedio: {resumen.get('productividad_promedio', 0)} unidades/h",
        "",
        "ALERTAS INTERNAS",
        *([f"- {a}" for a in alertas] or ["- Sin alertas internas destacadas."]),
        "",
        "TOP OPERARIOS",
        *[
            f"- {o['operario']}: {o['productividad_general']} unidades/h, "
            f"{o['cantidad_total']} unidades, {o['movimientos']} movimientos, "
            f"desvio {o['desvio_vs_promedio_pct']}%"
            for o in top
        ],
        "",
        "OPERARIOS CON MENOR PRODUCTIVIDAD",
        *[
            f"- {o['operario']}: {o['productividad_general']} unidades/h, "
            f"{o['cantidad_total']} unidades, {o['movimientos']} movimientos, "
            f"desvio {o['desvio_vs_promedio_pct']}%"
            for o in bottom
        ],
        "",
        "PRODUCTIVIDAD POR ZONA",
        *[
            f"- {z['zona']}: {z['productividad']} unidades/h, {z['cantidad_total']} unidades, "
            f"{z['movimientos']} movimientos, {z['operarios']} operarios"
            for z in zonas
        ],
        "",
        "COMPARATIVAS HISTORICAS",
        f"- Operarios con baseline historico: {historico.get('muestras_operario', 0)}",
        f"- Zonas con baseline historico: {historico.get('muestras_zona', 0)}",
        *[
            f"- Operario {o['operario']}: actual {o['actual']} vs historico {o['promedio_historico']} unidades/h "
            f"({o['delta_pct']}%) en {o['ventanas']} ventanas"
            for o in historico_bajos
        ],
        *[
            f"- Zona {z['zona']}: actual {z['actual']} vs historico {z['promedio_historico']} unidades/h "
            f"({z['delta_pct']}%) en {z['ventanas']} ventanas"
            for z in historico_zonas
        ],
    ])


async def build_or_get_ai_analysis(
    resumen_interno: dict[str, Any],
    provider: str,
    force_refresh: bool = False,
) -> dict[str, Any]:
    provider = (provider or os.getenv("AI_PROVIDER", "claude")).lower()
    rango = resumen_interno.get("rango", {})
    fecha_desde = rango.get("fecha_desde")
    fecha_hasta = rango.get("fecha_hasta")
    if not fecha_desde or not fecha_hasta:
        raise ValueError("El resumen interno no contiene rango fecha_desde/fecha_hasta.")

    resumen_hash = _hash_payload(resumen_interno)
    cached_row = None
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cached_row = await _get_cached_run(db, fecha_desde, fecha_hasta)
        if (
            not force_refresh
            and cached_row
            and cached_row["ia_json"]
            and cached_row["ia_provider"] == provider
            and cached_row["ia_prompt_version"] == AI_PROMPT_VERSION
            and cached_row["ia_summary_hash"] == resumen_hash
        ):
            payload = json.loads(cached_row["ia_json"])
            payload["cache"] = {
                "ia_cache_hit": True,
                "run_id": cached_row["run_id"],
                "ia_generated_at": cached_row["ia_generated_at"],
            }
            return payload

    context = _build_ai_context(resumen_interno)
    raw_text, model_used = await _call_ai(
        provider,
        SYSTEM_PRODUCTIVIDAD_ANALISIS,
        [{"role": "user", "content": context}],
    )
    parsed = json.loads(_extract_json(raw_text))
    payload = {
        "provider": provider,
        "model_used": model_used,
        "analisis": parsed,
        "cache": {
            "ia_cache_hit": False,
            "run_id": cached_row["run_id"] if cached_row else None,
        },
    }

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE productividad_analisis_runs
            SET ia_provider = ?,
                ia_model = ?,
                ia_prompt_version = ?,
                ia_summary_hash = ?,
                ia_json = ?,
                ia_generated_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE rango_key = ?
            """,
            (
                provider,
                model_used,
                AI_PROMPT_VERSION,
                resumen_hash,
                _canonical_json({
                    "provider": provider,
                    "model_used": model_used,
                    "analisis": parsed,
                }),
                _rango_key(fecha_desde, fecha_hasta),
            ),
        )
        await db.commit()

    return payload


@router.get("/analisis/interno")
async def get_analisis_interno(
    fecha_desde: str = Query(..., description="YYYY-MM-DD HH:MM:SS"),
    fecha_hasta: str = Query(..., description="YYYY-MM-DD HH:MM:SS"),
    force_refresh: bool = Query(False, description="Si true, rehace la consulta a Oracle"),
):
    dt_desde = _parse_dt(fecha_desde, "fecha_desde")
    dt_hasta = _parse_dt(fecha_hasta, "fecha_hasta")
    if dt_hasta <= dt_desde:
        raise HTTPException(status_code=400, detail="fecha_hasta debe ser mayor a fecha_desde")

    try:
        return await build_or_get_internal_analysis(fecha_desde, fecha_hasta, force_refresh=force_refresh)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    except Exception as exc:
        logger.exception("Error consultando BD productiva")
        raise HTTPException(status_code=500, detail=f"No se pudo consultar la BD productiva: {exc}")


@router.post("/analisis/ia")
async def post_analisis_ia(req: AnalisisIARequest):
    provider = (req.provider or os.getenv("AI_PROVIDER", "claude")).lower()

    try:
        return await build_or_get_ai_analysis(
            req.resumen_interno,
            provider=provider,
            force_refresh=req.force_refresh,
        )
    except Exception as exc:
        logger.exception("Error generando analisis IA")
        raise HTTPException(status_code=500, detail=f"No se pudo generar el analisis IA: {exc}")


async def _get_cached_picking_analysis_rows(fecha: str, turno_key: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT r.*
            FROM picking_analysis_cache_rows r
            JOIN picking_analysis_cache_runs run
              ON run.cache_run_id = r.cache_run_id
            WHERE run.fecha = ? AND run.turno_key = ?
            ORDER BY r.fh_movimiento, r.copecrea
            """,
            (fecha, turno_key),
        ) as cur:
            async for row in cur:
                rows.append(
                    {
                        "ALMACEN": row["almacen"],
                        "COPECREA": row["copecrea"],
                        "OPERARIO": row["operario"],
                        "FH_MOVIMIENTO": row["fh_movimiento"],
                        "ZONA_ORIGEN": row["zona_origen"],
                        "UBIC_ORIGEN": row["ubic_origen"],
                        "NRO_PALLET": row["nro_pallet"],
                        "CANTIDAD": row["cantidad"],
                        "PESO": row["peso"],
                        "REFERENCIA": row["referencia"],
                    }
                )
    return rows


async def _store_cached_picking_analysis_rows(
    *,
    fecha: str,
    turno_key: str,
    turno_label: str,
    fecha_desde: str,
    fecha_hasta: str,
    rows: list[dict[str, Any]],
    source_name: str = "oracle_productiva",
) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        existing = await db.execute(
            "SELECT cache_run_id FROM picking_analysis_cache_runs WHERE fecha = ? AND turno_key = ?",
            (fecha, turno_key),
        )
        existing_row = await existing.fetchone()
        if existing_row:
            cache_run_id = existing_row[0]
            await db.execute(
                "DELETE FROM picking_analysis_cache_rows WHERE cache_run_id = ?",
                (cache_run_id,),
            )
            await db.execute(
                """
                UPDATE picking_analysis_cache_runs
                SET turno_label = ?,
                    fecha_desde = ?,
                    fecha_hasta = ?,
                    source_name = ?,
                    source_rows_count = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE cache_run_id = ?
                """,
                (turno_label, fecha_desde, fecha_hasta, source_name, len(rows), cache_run_id),
            )
        else:
            cursor = await db.execute(
                """
                INSERT INTO picking_analysis_cache_runs (
                    fecha, turno_key, turno_label, fecha_desde, fecha_hasta, source_name, source_rows_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (fecha, turno_key, turno_label, fecha_desde, fecha_hasta, source_name, len(rows)),
            )
            cache_run_id = cursor.lastrowid

        payload = []
        for row in rows:
            fh_movimiento = str(row.get("FH_MOVIMIENTO") or "")
            copecrea = _safe_str(row.get("COPECREA"), "")
            ubic_origen = _safe_str(row.get("UBIC_ORIGEN"), "")
            nro_pallet = _safe_str(row.get("NRO_PALLET"), "")
            cantidad = _safe_float(row.get("CANTIDAD"))
            payload.append(
                (
                    _picking_cache_row_uid(fecha, turno_key, fh_movimiento, copecrea, ubic_origen, nro_pallet, cantidad),
                    cache_run_id,
                    fecha,
                    turno_key,
                    fh_movimiento,
                    copecrea,
                    _safe_str(row.get("OPERARIO"), ""),
                    _safe_str(row.get("ALMACEN"), "SIN MAPEAR"),
                    _safe_str(row.get("ZONA_ORIGEN"), ""),
                    ubic_origen,
                    nro_pallet,
                    cantidad,
                    _safe_float(row.get("PESO")),
                    _safe_str(row.get("REFERENCIA"), ""),
                )
            )
        await db.executemany(
            """
            INSERT OR REPLACE INTO picking_analysis_cache_rows (
                row_uid, cache_run_id, fecha, turno_key, fh_movimiento, copecrea, operario, almacen,
                zona_origen, ubic_origen, nro_pallet, cantidad, peso, referencia
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            payload,
        )
        await db.commit()
    return len(payload)


async def _get_picking_cache_run_row(fecha: str, turno_key: str) -> aiosqlite.Row | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT *
            FROM picking_analysis_cache_runs
            WHERE fecha = ? AND turno_key = ?
            LIMIT 1
            """,
            (fecha, turno_key),
        ) as cur:
            return await cur.fetchone()


async def _update_picking_cache_run_hash(
    *,
    fecha: str,
    turno_key: str,
    resumen_hash: str,
) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE picking_analysis_cache_runs
            SET resumen_hash = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE fecha = ? AND turno_key = ?
            """,
            (resumen_hash, fecha, turno_key),
        )
        await db.commit()


async def _update_picking_cache_run_ia(
    *,
    fecha: str,
    turno_key: str,
    provider: str,
    model_used: str,
    summary_hash: str,
    ia_payload: dict[str, Any],
) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE picking_analysis_cache_runs
            SET ia_provider = ?,
                ia_model = ?,
                ia_prompt_version = ?,
                ia_summary_hash = ?,
                ia_json = ?,
                ia_generated_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE fecha = ? AND turno_key = ?
            """,
            (
                provider,
                model_used,
                PICKING_ANALISIS_IA_PROMPT_VERSION,
                summary_hash,
                _canonical_json(ia_payload),
                fecha,
                turno_key,
            ),
        )
        await db.commit()


async def _load_ubicaciones_oracle_map() -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT
                ubicacion_codigo,
                czonalma,
                cpasillo,
                chuecopa,
                nnivelal,
                nposlarg,
                xsitubic,
                xtipsubi,
                crotacio
            FROM ubicaciones_oracle
            """
        ) as cur:
            async for row in cur:
                item = dict(row)
                codigo = _safe_str(item.get("ubicacion_codigo"), "")
                if codigo and codigo not in mapping:
                    mapping[codigo] = item
    return mapping


def _build_picking_row_difficulty(
    *,
    cantidad: float,
    peso: float,
    location_changed: bool,
    zone_changed: bool,
    passillo_changed: bool,
) -> float:
    difficulty = 1.0
    difficulty += min(max(cantidad, 0.0), 20.0) * 0.08
    difficulty += min(max(peso, 0.0), 80.0) * 0.03
    if location_changed:
        difficulty += 0.50
    if passillo_changed:
        difficulty += 0.35
    if zone_changed:
        difficulty += 0.75
    return round(difficulty, 4)


async def build_picking_base_analysis(fecha: str, turno: str, force_refresh: bool = False) -> dict[str, Any]:
    turno_key, fecha_desde, fecha_hasta = _turn_range_for_date(fecha, turno)
    detail_rows = [] if force_refresh else await _get_cached_picking_analysis_rows(fecha, turno_key)
    source_name = "sqlite_cache" if detail_rows else "oracle_productiva"
    if not detail_rows:
        detail_rows = await asyncio.to_thread(
            query_productive_db_picking_analysis_detail,
            fecha_desde,
            fecha_hasta,
        )
        await _store_cached_picking_analysis_rows(
            fecha=fecha,
            turno_key=turno_key,
            turno_label=_turn_label(turno_key),
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
            rows=detail_rows,
            source_name="oracle_productiva",
        )
    ubicaciones_map = await _load_ubicaciones_oracle_map()

    operarios: dict[str, dict[str, Any]] = {}
    almacenes = set()
    zonas = set()
    total_cantidad = 0.0
    total_peso = 0.0
    total_distancia = 0.0
    total_dificultad = 0.0
    detail_normalized = []

    for raw in detail_rows:
        legajo = _safe_str(raw.get("COPECREA"), "Sin legajo")
        nombre = _safe_str(raw.get("OPERARIO"), legajo)
        fh_text = str(raw.get("FH_MOVIMIENTO") or "")
        fh_dt = _parse_dt(fh_text.replace("T", " ")[:19], "fh_movimiento") if fh_text else None
        zona_origen = _safe_str(raw.get("ZONA_ORIGEN"), "SIN DATO")
        ubic_origen = _safe_str(raw.get("UBIC_ORIGEN"), "")
        almacen = _safe_str(raw.get("ALMACEN"), "SIN MAPEAR")
        pallet = _safe_str(raw.get("NRO_PALLET"), "")
        cantidad = round(_safe_float(raw.get("CANTIDAD")), 2)
        peso = round(_safe_float(raw.get("PESO")), 2)

        parsed_ubic = _parse_ubic_origen(ubic_origen)
        ubic_meta = ubicaciones_map.get(ubic_origen, {})
        cpasillo = _safe_str(ubic_meta.get("cpasillo"), parsed_ubic[0] if parsed_ubic else "")
        chuecopa = ubic_meta.get("chuecopa", parsed_ubic[1] if parsed_ubic else None)
        nposlarg = ubic_meta.get("nposlarg", parsed_ubic[2] if parsed_ubic else None)

        current = operarios.get(legajo)
        if not current:
            current = {
                "copecrea": legajo,
                "operario": nombre,
                "lineas": 0,
                "cantidad_total": 0.0,
                "peso_total": 0.0,
                "pallets": set(),
                "seg_total": 0.0,
                "prev_dt": None,
                "prev_ubic": "",
                "prev_zona": "",
                "prev_pasillo": "",
                "distancia_estimada_m": 0.0,
                "cambios_ubicacion": 0,
                "dificultad_total": 0.0,
                "almacenes": defaultdict(int),
                "zonas": defaultdict(int),
                "pasillos": defaultdict(int),
                "primer_mov_dt": fh_dt,
                "ultimo_mov_dt": fh_dt,
                "detail_rows": [],
            }
            operarios[legajo] = current

        location_changed = bool(current["prev_ubic"] and ubic_origen and current["prev_ubic"] != ubic_origen)
        zone_changed = bool(current["prev_zona"] and zona_origen and current["prev_zona"] != zona_origen)
        passillo_changed = bool(current["prev_pasillo"] and cpasillo and current["prev_pasillo"] != cpasillo)
        distance_m = 1.0 if location_changed else 0.0
        difficulty = _build_picking_row_difficulty(
            cantidad=cantidad,
            peso=peso,
            location_changed=location_changed,
            zone_changed=zone_changed,
            passillo_changed=passillo_changed,
        )

        current["lineas"] += 1
        current["cantidad_total"] += cantidad
        current["peso_total"] += peso
        current["distancia_estimada_m"] += distance_m
        current["dificultad_total"] += difficulty
        current["almacenes"][almacen] += 1
        current["zonas"][zona_origen] += 1
        if cpasillo:
            current["pasillos"][cpasillo] += 1
        if location_changed:
            current["cambios_ubicacion"] += 1
        if pallet:
            current["pallets"].add(pallet)
        if fh_dt:
            if not current["primer_mov_dt"] or fh_dt < current["primer_mov_dt"]:
                current["primer_mov_dt"] = fh_dt
            if not current["ultimo_mov_dt"] or fh_dt > current["ultimo_mov_dt"]:
                current["ultimo_mov_dt"] = fh_dt
            if current["prev_dt"] is not None:
                current["seg_total"] += max((fh_dt - current["prev_dt"]).total_seconds(), 0.0)
            current["prev_dt"] = fh_dt
        current["prev_ubic"] = ubic_origen or current["prev_ubic"]
        current["prev_zona"] = zona_origen or current["prev_zona"]
        current["prev_pasillo"] = cpasillo or current["prev_pasillo"]

        detail_item = {
            "copecrea": legajo,
            "operario": nombre,
            "fh_movimiento": fh_text,
            "almacen": almacen,
            "zona_origen": zona_origen,
            "ubic_origen": ubic_origen,
            "cpasillo": cpasillo,
            "chuecopa": chuecopa,
            "nposlarg": nposlarg,
            "nro_pallet": pallet,
            "cantidad": cantidad,
            "peso": peso,
            "distancia_estimada_m": distance_m,
            "dificultad_fila": difficulty,
        }
        current["detail_rows"].append(detail_item)
        detail_normalized.append(detail_item)

        almacenes.add(almacen)
        zonas.add(zona_origen)
        total_cantidad += cantidad
        total_peso += peso
        total_distancia += distance_m
        total_dificultad += difficulty

    rows = []
    difficulty_indexes = []
    cantidad_horas = []
    for current in operarios.values():
        hs_totales = round(current["seg_total"] / 3600, 2) if current["seg_total"] > 0 else 0.0
        cantidad_hora = round(current["cantidad_total"] / hs_totales, 2) if hs_totales > 0 else 0.0
        kg_hora = round(current["peso_total"] / hs_totales, 2) if hs_totales > 0 else 0.0
        dificultad_promedio = round(current["dificultad_total"] / max(current["lineas"], 1), 2)
        difficulty_indexes.append(dificultad_promedio)
        cantidad_horas.append(cantidad_hora)
        rows.append(
            {
                "copecrea": current["copecrea"],
                "operario": current["operario"],
                "almacen_principal": _counter_top(current["almacenes"], "SIN MAPEAR"),
                "zona_principal": _counter_top(current["zonas"], "SIN DATO"),
                "pasillo_principal": _counter_top(current["pasillos"], "SIN DATO"),
                "primer_mov": current["primer_mov_dt"].strftime("%Y-%m-%d %H:%M:%S") if current["primer_mov_dt"] else "",
                "ultimo_mov": current["ultimo_mov_dt"].strftime("%Y-%m-%d %H:%M:%S") if current["ultimo_mov_dt"] else "",
                "lineas": current["lineas"],
                "cantidad_total": round(current["cantidad_total"], 2),
                "peso_total": round(current["peso_total"], 2),
                "pallets_distintos": len(current["pallets"]),
                "hs_totales": hs_totales,
                "cantidad_hora": cantidad_hora,
                "kg_hora": kg_hora,
                "distancia_estimada_m": round(current["distancia_estimada_m"], 2),
                "cambios_ubicacion": current["cambios_ubicacion"],
                "dificultad_total": round(current["dificultad_total"], 2),
                "indice_dificultad": dificultad_promedio,
            }
        )

    avg_difficulty = statistics.mean(difficulty_indexes) if difficulty_indexes else 1.0
    avg_cantidad_hora = statistics.mean(cantidad_horas) if cantidad_horas else 0.0

    for row in rows:
        factor_dificultad = _clamp((row["indice_dificultad"] / avg_difficulty) if avg_difficulty > 0 else 1.0, 0.75, 1.35)
        productividad_ajustada = round(row["cantidad_hora"] * factor_dificultad, 2)
        suerte_asignacion_pct = round(((avg_difficulty - row["indice_dificultad"]) / avg_difficulty) * 100, 2) if avg_difficulty > 0 else 0.0
        row["factor_dificultad"] = round(factor_dificultad, 3)
        row["productividad_ajustada"] = productividad_ajustada
        row["suerte_asignacion_pct"] = suerte_asignacion_pct
        row["gap_vs_promedio_bruto_pct"] = round(((row["cantidad_hora"] - avg_cantidad_hora) / avg_cantidad_hora) * 100, 2) if avg_cantidad_hora > 0 else 0.0
        row["gap_vs_promedio_ajustado_pct"] = round(((productividad_ajustada - avg_cantidad_hora) / avg_cantidad_hora) * 100, 2) if avg_cantidad_hora > 0 else 0.0
        if suerte_asignacion_pct >= 10:
            row["lectura_suerte"] = "Asignacion relativamente facil"
        elif suerte_asignacion_pct <= -10:
            row["lectura_suerte"] = "Asignacion relativamente dificil"
        else:
            row["lectura_suerte"] = "Asignacion equilibrada"

    rows.sort(
        key=lambda item: (
            -item["productividad_ajustada"],
            -item["cantidad_hora"],
            item["operario"],
        )
    )
    for idx, row in enumerate(rows, start=1):
        row["ranking_ajustado"] = idx

    rows_bruto = sorted(rows, key=lambda item: (-item["cantidad_hora"], item["operario"]))
    ranking_bruto = {row["copecrea"]: idx for idx, row in enumerate(rows_bruto, start=1)}
    for row in rows:
        row["ranking_bruto"] = ranking_bruto.get(row["copecrea"], 0)
        row["delta_ranking"] = row["ranking_bruto"] - row["ranking_ajustado"]

    inequidad = []
    for row in sorted(rows, key=lambda item: item["suerte_asignacion_pct"]):
        if row["suerte_asignacion_pct"] <= -12:
            inequidad.append(
                {
                    "tipo": "dificultad_alta",
                    "operario": row["operario"],
                    "copecrea": row["copecrea"],
                    "zona_principal": row["zona_principal"],
                    "indice_dificultad": row["indice_dificultad"],
                    "suerte_asignacion_pct": row["suerte_asignacion_pct"],
                }
            )
    for row in sorted(rows, key=lambda item: item["suerte_asignacion_pct"], reverse=True):
        if row["suerte_asignacion_pct"] >= 12:
            inequidad.append(
                {
                    "tipo": "dificultad_baja",
                    "operario": row["operario"],
                    "copecrea": row["copecrea"],
                    "zona_principal": row["zona_principal"],
                    "indice_dificultad": row["indice_dificultad"],
                    "suerte_asignacion_pct": row["suerte_asignacion_pct"],
                }
            )
    inequidad = inequidad[:8]

    comparaciones = []
    for i, left in enumerate(rows):
        for right in rows[i + 1:]:
            if left["zona_principal"] != right["zona_principal"]:
                continue
            max_difficulty = max(left["indice_dificultad"], right["indice_dificultad"], 0.01)
            difficulty_gap_pct = abs(left["indice_dificultad"] - right["indice_dificultad"]) / max_difficulty * 100
            if difficulty_gap_pct > 12:
                continue
            cantidad_gap_pct = abs(left["cantidad_hora"] - right["cantidad_hora"]) / max(max(left["cantidad_hora"], right["cantidad_hora"]), 0.01) * 100
            if cantidad_gap_pct < 25:
                continue
            comparaciones.append(
                {
                    "zona_principal": left["zona_principal"],
                    "operario_a": left["operario"],
                    "operario_b": right["operario"],
                    "cantidad_hora_a": left["cantidad_hora"],
                    "cantidad_hora_b": right["cantidad_hora"],
                    "productividad_ajustada_a": left["productividad_ajustada"],
                    "productividad_ajustada_b": right["productividad_ajustada"],
                    "indice_dificultad_a": left["indice_dificultad"],
                    "indice_dificultad_b": right["indice_dificultad"],
                    "brecha_productividad_pct": round(cantidad_gap_pct, 2),
                }
            )
    comparaciones.sort(key=lambda item: item["brecha_productividad_pct"], reverse=True)

    explanation = {
        "metrica_principal": "cantidad/hora",
        "supuestos": [
            "Cada fila de Picking se toma como una accion registrada.",
            "La distancia estimada suma 1 metro cuando el operario cambia de ubicacion entre dos picks consecutivos.",
            "La productividad ajustada toma la cantidad/hora y la normaliza por la dificultad promedio asignada.",
            "La suerte de asignacion es relativa al promedio del turno consultado.",
            "Los coeficientes 0.08 para cantidad y 0.03 para peso son ponderaciones heuristicas iniciales del V0; no representan todavia una calibracion estadistica cerrada del negocio.",
        ],
        "formulas": [
            "Cantidad/hora = cantidad_total / horas_activas.",
            "Horas activas = suma de diferencias entre movimientos consecutivos del mismo operario.",
            "Dificultad fila = 1 + (cantidad * 0.08) + (peso * 0.03) + bonos por cambio de ubicacion/pasillo/zona.",
            "Indice de dificultad = dificultad_total / lineas.",
            "Productividad ajustada = cantidad/hora * factor_dificultad, con factor acotado entre 0.75 y 1.35.",
            "Suerte asignacion % = (dificultad_promedio_turno - dificultad_operario) / dificultad_promedio_turno * 100.",
        ],
    }

    payload = {
        "fecha": fecha,
        "turno": _turn_label(turno_key),
        "turno_key": turno_key,
        "fecha_desde": fecha_desde,
        "fecha_hasta": fecha_hasta,
        "rows": rows,
        "detail_rows": detail_normalized,
        "summary": {
            "operarios": len(rows),
            "movimientos": len(detail_normalized),
            "cantidad_total": round(total_cantidad, 2),
            "peso_total": round(total_peso, 2),
            "distancia_estimada_total_m": round(total_distancia, 2),
            "dificultad_promedio": round(avg_difficulty, 2),
            "cantidad_hora_promedio": round(avg_cantidad_hora, 2),
            "almacenes": len(almacenes),
            "zonas": len(zonas),
            "source_name": source_name,
        },
        "insights": {
            "top_ajustado": rows[:5],
            "top_bruto": rows_bruto[:5],
            "inequidad_asignacion": inequidad,
            "comparaciones_similares": comparaciones[:6],
        },
        "filters": {
            "almacenes": sorted(almacenes),
            "operaciones": ["PICKING"],
            "estados": ["ALL"],
        },
        "explanation": explanation,
        "cache": {
            "source_name": source_name,
            "force_refresh": force_refresh,
        },
    }
    resumen_hash = _hash_payload(payload)
    payload["cache"]["summary_hash"] = resumen_hash
    await _update_picking_cache_run_hash(
        fecha=fecha,
        turno_key=turno_key,
        resumen_hash=resumen_hash,
    )
    return payload


def _build_picking_ia_context(analisis_base: dict[str, Any]) -> str:
    summary = analisis_base.get("summary", {})
    rows = analisis_base.get("rows", [])[:8]
    insights = analisis_base.get("insights", {})
    inequidad = insights.get("inequidad_asignacion", [])[:5]
    comparaciones = insights.get("comparaciones_similares", [])[:5]

    lines = [
        "ANALISIS BASE DE PICKING",
        f"Fecha: {analisis_base.get('fecha')}",
        f"Turno: {analisis_base.get('turno')}",
        "",
        "RESUMEN",
        f"- Operarios: {summary.get('operarios', 0)}",
        f"- Movimientos: {summary.get('movimientos', 0)}",
        f"- Cantidad total: {summary.get('cantidad_total', 0)}",
        f"- Peso total: {summary.get('peso_total', 0)}",
        f"- Cantidad/hora promedio: {summary.get('cantidad_hora_promedio', 0)}",
        f"- Dificultad promedio: {summary.get('dificultad_promedio', 0)}",
        "",
        "OPERARIOS DESTACADOS",
    ]
    lines.extend(
        [
            f"- {row['operario']}: bruto {row['cantidad_hora']} /h, ajustado {row['productividad_ajustada']} /h, dificultad {row['indice_dificultad']}, suerte {row['suerte_asignacion_pct']}%"
            for row in rows
        ]
        or ["- Sin operarios con datos."]
    )
    lines.append("")
    lines.append("POSIBLES INEQUIDADES")
    lines.extend(
        [
            f"- {item['operario']}: {item['tipo']}, dificultad {item['indice_dificultad']}, suerte {item['suerte_asignacion_pct']}%"
            for item in inequidad
        ]
        or ["- Sin casos marcados."]
    )
    lines.append("")
    lines.append("COMPARACIONES BAJO CONDICIONES SIMILARES")
    lines.extend(
        [
            f"- Zona {item['zona_principal']}: {item['operario_a']} {item['cantidad_hora_a']}/h vs {item['operario_b']} {item['cantidad_hora_b']}/h con dificultad {item['indice_dificultad_a']} vs {item['indice_dificultad_b']}."
            for item in comparaciones
        ]
        or ["- Sin comparaciones fuertes."]
    )
    return "\n".join(lines)


@router.get("/picking/base")
async def get_picking_base_analysis(
    fecha: str = Query(..., description="YYYY-MM-DD"),
    turno: str = Query(..., description="Mañana, Tarde o Noche"),
    force_refresh: bool = Query(False, description="Si true, rehace la consulta a Oracle y refresca cache local"),
):
    try:
        return await build_picking_base_analysis(fecha, turno, force_refresh=force_refresh)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    except Exception as exc:
        logger.exception("Error generando analisis base de picking")
        raise HTTPException(status_code=500, detail=f"No se pudo generar el analisis base de picking: {exc}")


@router.post("/picking/ia")
async def post_picking_analysis_ia(req: PickingAnalisisIARequest):
    provider = (req.provider or os.getenv("AI_PROVIDER", "claude")).lower()
    try:
        summary = req.analisis_base.get("summary", {}) if isinstance(req.analisis_base, dict) else {}
        fecha = _safe_str(req.analisis_base.get("fecha"), "")
        turno_key = _safe_str(req.analisis_base.get("turno_key"), "")
        summary_hash = _safe_str(req.analisis_base.get("cache", {}).get("summary_hash"), "") or _hash_payload(req.analisis_base)
        if fecha and turno_key:
            cached_row = await _get_picking_cache_run_row(fecha, turno_key)
            if (
                cached_row
                and cached_row["ia_json"]
                and cached_row["ia_provider"] == provider
                and cached_row["ia_prompt_version"] == PICKING_ANALISIS_IA_PROMPT_VERSION
                and cached_row["ia_summary_hash"] == summary_hash
            ):
                cached_payload = json.loads(cached_row["ia_json"])
                cached_payload["cache"] = {
                    "ia_cache_hit": True,
                    "ia_generated_at": cached_row["ia_generated_at"],
                }
                logger.info(
                    "[picking-ia] Cache hit fecha=%s turno=%s provider=%s",
                    fecha,
                    turno_key,
                    provider,
                )
                return cached_payload

        logger.info(
            "[picking-ia] Ejecutar IA solicitado fecha=%s turno=%s provider=%s source=%s operarios=%s movimientos=%s",
            fecha,
            req.analisis_base.get("turno"),
            provider,
            req.analisis_base.get("cache", {}).get("source_name") or summary.get("source_name"),
            summary.get("operarios"),
            summary.get("movimientos"),
        )
        context = _build_picking_ia_context(req.analisis_base)
        raw_text, model_used = await _call_ai(
            provider,
            SYSTEM_PICKING_ANALISIS_IA,
            [{"role": "user", "content": context}],
        )
        parsed = json.loads(_extract_json(raw_text))
        payload = {
            "provider": provider,
            "model_used": model_used,
            "analisis": parsed,
            "cache": {
                "ia_cache_hit": False,
            },
        }
        if fecha and turno_key:
            await _update_picking_cache_run_ia(
                fecha=fecha,
                turno_key=turno_key,
                provider=provider,
                model_used=model_used,
                summary_hash=summary_hash,
                ia_payload={
                    "provider": provider,
                    "model_used": model_used,
                    "analisis": parsed,
                },
            )
        return payload
    except Exception as exc:
        logger.exception("Error generando lectura IA de picking")
        raise HTTPException(status_code=500, detail=f"No se pudo generar la lectura IA de picking: {exc}")


@router.get("/online")
async def get_productividad_online(
    fecha: str = Query(..., description="YYYY-MM-DD"),
    turno: str = Query(..., description="Mañana, Tarde o Noche"),
):
    turno_key, fecha_desde, fecha_hasta = _turn_range_for_date(fecha, turno)
    allowed_operations = _allowed_online_operations()

    logger.info(
        "[productividad-online] Consultando Oracle turno=%s rango=%s..%s",
        _turn_label(turno_key),
        fecha_desde,
        fecha_hasta,
    )
    try:
        detail_rows = await asyncio.to_thread(query_productive_db_online, fecha_desde, fecha_hasta)
        logger.info("[productividad-online] Oracle OK: %s movimientos", len(detail_rows))
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    except Exception as exc:
        logger.exception("Error consultando productividad online")
        raise HTTPException(status_code=500, detail=f"No se pudo consultar Oracle: {exc}")

    normalized_rows = []
    normalized_detail_rows = []
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    almacenes = set()
    operaciones = set()
    operarios_unicos = set()
    operarios_online = set()
    now_dt = datetime.now()

    for row in detail_rows:
        operacion = _normalize_operacion_name(_safe_str(row.get("OPERACION")))
        if allowed_operations and operacion not in allowed_operations:
            continue
        almacen = _safe_str(row.get("ALMACEN"), "SIN MAPEAR")
        legajo = _safe_str(row.get("COPECREA"))
        operario = _safe_str(row.get("OPERARIO"))
        fh_text = str(row.get("FH_MOVIMIENTO") or "")
        fh_dt = _parse_dt(fh_text.replace("T", " ")[:19], "fh_movimiento") if fh_text else None
        cantidad = round(_safe_float(row.get("CANTIDAD")), 2)
        peso = round(_safe_float(row.get("PESO")), 2)
        pallet = _safe_str(row.get("NRO_PALLET"))
        zona_origen = _safe_str(row.get("ZONA_ORIGEN"), "")
        ubic_origen = _safe_str(row.get("UBIC_ORIGEN"), "")

        normalized_detail_rows.append(
            {
                "almacen": almacen,
                "copecrea": legajo,
                "operario": operario,
                "operacion": operacion,
                "fh_movimiento": fh_text,
                "zona_origen": zona_origen,
                "ubic_origen": ubic_origen,
                "nro_pallet": pallet,
                "cantidad": cantidad,
                "peso": peso,
            }
        )

        almacenes.add(almacen)
        operaciones.add(operacion)
        if legajo:
            operarios_unicos.add(legajo)

        key = (almacen, legajo, operacion)
        current = grouped.get(key)
        if not current:
            current = {
                "almacen": almacen,
                "copecrea": legajo,
                "operario": operario,
                "operacion": operacion,
                "primer_mov_dt": fh_dt,
                "ultimo_mov_dt": fh_dt,
                "lineas": 0,
                "cantidad_total": 0.0,
                "peso_total": 0.0,
                "pallets": set(),
                "seg_total": 0.0,
                "prev_dt": None,
            }
            grouped[key] = current

        current["lineas"] += 1
        current["cantidad_total"] += cantidad
        current["peso_total"] += peso
        if pallet:
            current["pallets"].add(pallet)
        if fh_dt:
            if not current["primer_mov_dt"] or fh_dt < current["primer_mov_dt"]:
                current["primer_mov_dt"] = fh_dt
            if not current["ultimo_mov_dt"] or fh_dt > current["ultimo_mov_dt"]:
                current["ultimo_mov_dt"] = fh_dt
            if current["prev_dt"] is not None:
                current["seg_total"] += max((fh_dt - current["prev_dt"]).total_seconds(), 0.0)
            current["prev_dt"] = fh_dt

    for current in grouped.values():
        primer = current["primer_mov_dt"]
        ultimo = current["ultimo_mov_dt"]
        minutos_activos = round(max(((ultimo - primer).total_seconds() / 60), 0.0), 1) if primer and ultimo else 0.0
        hs_totales = round(current["seg_total"] / 3600, 2) if current["seg_total"] > 0 else 0.0
        cantidad_hora = round(current["cantidad_total"] / hs_totales, 2) if hs_totales > 0 else 0.0
        kg_hora = round(current["peso_total"] / hs_totales, 2) if hs_totales > 0 else 0.0
        estado = "ONLINE" if ultimo and (now_dt - ultimo).total_seconds() <= 600 else "INACTIVO"
        if current["copecrea"]:
            if estado == "ONLINE":
                operarios_online.add(current["copecrea"])
        normalized_rows.append(
            {
                "almacen": current["almacen"],
                "copecrea": current["copecrea"],
                "operario": current["operario"],
                "operacion": current["operacion"],
                "primer_mov": primer.strftime("%Y-%m-%d %H:%M:%S") if primer else "",
                "ultimo_mov": ultimo.strftime("%Y-%m-%d %H:%M:%S") if ultimo else "",
                "minutos_activos": minutos_activos,
                "lineas": current["lineas"],
                "cantidad_total": round(current["cantidad_total"], 2),
                "peso_total": round(current["peso_total"], 2),
                "pallets_distintos": len(current["pallets"]),
                "hs_totales": hs_totales,
                "cantidad_hora": cantidad_hora,
                "kg_hora": kg_hora,
                "estado": estado,
            }
        )

    normalized_rows.sort(
        key=lambda item: (
            item["almacen"],
            item["copecrea"],
            item["operacion"],
        )
    )
    logger.info(
        "[productividad-online] Agregado listo: %s filas resumen, %s movimientos detalle, %s operaciones configuradas",
        len(normalized_rows),
        len(normalized_detail_rows),
        len(allowed_operations),
    )

    return {
        "fecha": fecha,
        "turno": _turn_label(turno_key),
        "turno_key": turno_key,
        "fecha_desde": fecha_desde,
        "fecha_hasta": fecha_hasta,
        "rows": normalized_rows,
        "detail_rows": normalized_detail_rows,
        "summary": {
            "filas": len(normalized_rows),
            "operarios_unicos": len(operarios_unicos),
            "online": len(operarios_online),
            "inactivos": len(operarios_unicos - operarios_online),
            "almacenes": len(almacenes),
            "operaciones": len(operaciones),
        },
        "filters": {
            "almacenes": sorted(almacenes),
            "operaciones": sorted(operaciones),
            "estados": ["ONLINE", "INACTIVO"],
        },
    }
