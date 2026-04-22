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
import os
import subprocess
from collections import defaultdict
from datetime import datetime
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


class AnalisisIARequest(BaseModel):
    provider: str | None = None
    resumen_interno: dict[str, Any]
    force_refresh: bool = False


def _parse_dt(value: str, field_name: str) -> datetime:
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"{field_name} debe tener formato YYYY-MM-DD HH:MM:SS",
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


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_payload(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _query_productive_db(fecha_desde: str, fecha_hasta: str) -> list[dict[str, Any]]:
    if os.getenv("PRODUCTIVE_DB_USE_JDBC", "1").strip().lower() in {"1", "true", "yes", "si"}:
        return _query_productive_db_via_jdbc(fecha_desde, fecha_hasta)

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
            QUERY_PRODUCTIVIDAD,
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


def _query_productive_db_via_jdbc(fecha_desde: str, fecha_hasta: str) -> list[dict[str, Any]]:
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
    if not force_refresh:
        cached = await _get_cached_internal_summary(fecha_desde, fecha_hasta)
        if cached:
            return cached

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
