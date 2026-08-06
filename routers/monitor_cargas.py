"""Monitor online de bultos y volumen cargados en viajes abiertos."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from routers.productividad_analisis import _query_productive_db_sql


router = APIRouter(prefix="/api/monitor-cargas", tags=["monitor-cargas"])
logger = logging.getLogger("vigia.monitor_cargas")

MONITOR_CACHE_SECONDS = 20
_monitor_cache: dict[str, Any] = {"expires_at": 0.0, "payload": None}
_monitor_lock: asyncio.Lock | None = None


QUERY_MONITOR_CARGAS = """
WITH VIAJES AS (
    SELECT
        V.CEMPRESA,
        V.CCENTDIS,
        V.CNUVIAJE,
        V.HOJARUTA,
        V.CAMIMATR,
        V.CNUANDEN,
        V.CDIVISIO,
        V.CARGADOR,
        V.FCREAREG,
        V.FEAPERTU,
        V.FMODIREG,
        V.CSITVIAJ,
        T.QPALMAXI,
        T.QVOLMAXI
    FROM F810VIAJ V
    LEFT JOIN F811TRAI T
      ON T.CEMPRESA = V.CEMPRESA
     AND T.CAMIMATR = V.CAMIMATR
    WHERE V.CSITVIAJ = 'EP'
),
EXPEDICIONES AS (
    SELECT
        V.CEMPRESA,
        V.CCENTDIS,
        V.CNUVIAJE,
        E.CNUMEXPE,
        E.CSITEXPE,
        E.FCREACIO,
        E.QTBULTOS AS BULTOS_F035,
        E.QVOLTOTA AS VOLUMEN_F035
    FROM VIAJES V
    JOIN F035EXPE E
      ON E.CEMPRESA = V.CEMPRESA
     AND E.CCENTDIS = V.CCENTDIS
     AND E.CNUVIAJE = V.CNUVIAJE
),
PALLETS AS (
    SELECT
        E.CEMPRESA,
        E.CCENTDIS,
        E.CNUVIAJE,
        E.CNUMEXPE,
        P.CALMACEN,
        P.CNUPALET,
        P.QTBULTOS,
        P.QVOLTOTA,
        P.CSITPALS,
        P.CTIPTRAB,
        P.CTIPPALS
    FROM EXPEDICIONES E
    JOIN F080CPSA P
      ON P.CEMPRESA = E.CEMPRESA
     AND P.CNUMEXPE = E.CNUMEXPE
    WHERE NVL(P.XANULADA, 'N') <> 'S'
),
LINEAS_ACTIVAS AS (
    SELECT
        P.CEMPRESA,
        P.CCENTDIS,
        P.CNUVIAJE,
        P.CNUMEXPE,
        P.CALMACEN,
        P.CNUPALET,
        L.CREFEPLA,
        L.CVARLPLA,
        L.CCNSGPRO,
        L.QCANTIDA
    FROM PALLETS P
    JOIN F081LPSA L
      ON L.CEMPRESA = P.CEMPRESA
     AND L.CALMACEN = P.CALMACEN
     AND L.CNUPALET = P.CNUPALET
),
CLAVES_VLOG AS (
    SELECT DISTINCT
        CEMPRESA,
        CCNSGPRO,
        CREFEPLA,
        CVARLPLA
    FROM LINEAS_ACTIVAS
),
VLOG AS (
    SELECT
        G.CEMPRESA,
        G.CCONSIGN,
        G.CREFEREN,
        G.CVARLOGI,
        MAX(G.CCNIVELE) AS CCNIVELE,
        MAX(G.QCANTDEP) AS QCANTDEP,
        MAX(G.NALTUEXP) AS NALTUEXP,
        MAX(G.NANCHEXP) AS NANCHEXP,
        MAX(G.NLONGEXP) AS NLONGEXP,
        COUNT(*) AS COINCIDENCIAS
    FROM F054VLOG G
    JOIN CLAVES_VLOG K
      ON K.CEMPRESA = G.CEMPRESA
     AND K.CCNSGPRO = G.CCONSIGN
     AND K.CREFEPLA = G.CREFEREN
     AND K.CVARLPLA = G.CVARLOGI
    GROUP BY
        G.CEMPRESA,
        G.CCONSIGN,
        G.CREFEREN,
        G.CVARLOGI
),
LINEAS_PALLET AS (
    SELECT
        L.CEMPRESA,
        L.CNUVIAJE,
        L.CNUMEXPE,
        L.CALMACEN,
        L.CNUPALET,
        COUNT(*) AS LINEAS,
        SUM(
            CASE G.CCNIVELE
                WHEN 2 THEN L.QCANTIDA
                WHEN 3 THEN L.QCANTIDA * G.QCANTDEP
                ELSE 0
            END
        ) AS BULTOS_CALCULADOS,
        SUM(
            CASE
                WHEN G.NALTUEXP > 0
                 AND G.NANCHEXP > 0
                 AND G.NLONGEXP > 0
                THEN L.QCANTIDA * G.NALTUEXP * G.NANCHEXP * G.NLONGEXP / 1000
                ELSE 0
            END
        ) AS VOLUMEN_CALCULADO,
        SUM(
            CASE
                WHEN NVL(L.QCANTIDA, 0) > 0
                 AND G.CREFEREN IS NULL
                THEN 1 ELSE 0
            END
        ) AS LINEAS_SIN_VLOG,
        SUM(
            CASE
                WHEN NVL(L.QCANTIDA, 0) > 0
                 AND (
                     NVL(G.NALTUEXP, 0) <= 0
                     OR NVL(G.NANCHEXP, 0) <= 0
                     OR NVL(G.NLONGEXP, 0) <= 0
                 )
                THEN 1 ELSE 0
            END
        ) AS LINEAS_SIN_DIMENSION,
        SUM(
            CASE
                WHEN NVL(L.QCANTIDA, 0) > 0
                 AND NVL(G.CCNIVELE, -1) NOT IN (2, 3)
                THEN 1 ELSE 0
            END
        ) AS LINEAS_NIVEL_INVALIDO,
        SUM(
            CASE
                WHEN NVL(L.QCANTIDA, 0) > 0
                 AND NVL(G.COINCIDENCIAS, 0) > 1
                THEN 1 ELSE 0
            END
        ) AS LINEAS_VLOG_DUPLICADA
    FROM LINEAS_ACTIVAS L
    LEFT JOIN VLOG G
      ON G.CEMPRESA = L.CEMPRESA
     AND G.CCONSIGN = L.CCNSGPRO
     AND G.CREFEREN = L.CREFEPLA
     AND G.CVARLOGI = L.CVARLPLA
    GROUP BY
        L.CEMPRESA,
        L.CNUVIAJE,
        L.CNUMEXPE,
        L.CALMACEN,
        L.CNUPALET
),
CARGA_EXPEDICION AS (
    SELECT
        P.CEMPRESA,
        P.CNUVIAJE,
        P.CNUMEXPE,
        COUNT(*) AS PALLETS,
        SUM(NVL(L.LINEAS, 0)) AS LINEAS,
        SUM(NVL(L.BULTOS_CALCULADOS, 0)) AS BULTOS_CALCULADOS,
        SUM(NVL(L.VOLUMEN_CALCULADO, 0)) AS VOLUMEN_CALCULADO,
        SUM(P.QTBULTOS) AS BULTOS_F080,
        SUM(P.QVOLTOTA) AS VOLUMEN_F080,
        SUM(
            CASE
                WHEN L.CNUPALET IS NULL
                 AND (NVL(P.QTBULTOS, 0) > 0 OR NVL(P.QVOLTOTA, 0) > 0)
                THEN 1 ELSE 0
            END
        ) AS PALLETS_SIN_DETALLE,
        SUM(NVL(L.LINEAS_SIN_VLOG, 0)) AS LINEAS_SIN_VLOG,
        SUM(NVL(L.LINEAS_SIN_DIMENSION, 0)) AS LINEAS_SIN_DIMENSION,
        SUM(NVL(L.LINEAS_NIVEL_INVALIDO, 0)) AS LINEAS_NIVEL_INVALIDO,
        SUM(NVL(L.LINEAS_VLOG_DUPLICADA, 0)) AS LINEAS_VLOG_DUPLICADA
    FROM PALLETS P
    LEFT JOIN LINEAS_PALLET L
      ON L.CEMPRESA = P.CEMPRESA
     AND L.CNUVIAJE = P.CNUVIAJE
     AND L.CNUMEXPE = P.CNUMEXPE
     AND L.CALMACEN = P.CALMACEN
     AND L.CNUPALET = P.CNUPALET
    GROUP BY
        P.CEMPRESA,
        P.CNUVIAJE,
        P.CNUMEXPE
)
SELECT
    V.CEMPRESA,
    V.CCENTDIS,
    V.CNUVIAJE,
    V.HOJARUTA,
    V.CAMIMATR,
    V.CNUANDEN,
    V.CDIVISIO,
    CASE
        WHEN V.CDIVISIO IN (1, 3) THEN 'SECOS'
        WHEN V.CDIVISIO IN (2, 4) THEN 'REFRIGERADOS'
        WHEN V.CDIVISIO = 6 THEN 'NOA'
        ELSE 'OTROS'
    END AS DIVISION,
    V.CARGADOR,
    V.FCREAREG,
    V.FEAPERTU,
    V.FMODIREG,
    V.QPALMAXI,
    V.QVOLMAXI,
    E.CNUMEXPE,
    E.CSITEXPE,
    E.FCREACIO AS FECHA_EXPEDICION,
    NVL(C.PALLETS, 0) AS PALLETS,
    NVL(C.LINEAS, 0) AS LINEAS,
    NVL(C.BULTOS_CALCULADOS, 0) AS BULTOS_CALCULADOS,
    ROUND(NVL(C.VOLUMEN_CALCULADO, 0), 3) AS VOLUMEN_CALCULADO,
    NVL(C.BULTOS_F080, 0) AS BULTOS_F080,
    ROUND(NVL(C.VOLUMEN_F080, 0), 3) AS VOLUMEN_F080,
    NVL(E.BULTOS_F035, 0) AS BULTOS_F035,
    ROUND(NVL(E.VOLUMEN_F035, 0), 3) AS VOLUMEN_F035,
    NVL(C.PALLETS_SIN_DETALLE, 0) AS PALLETS_SIN_DETALLE,
    NVL(C.LINEAS_SIN_VLOG, 0) AS LINEAS_SIN_VLOG,
    NVL(C.LINEAS_SIN_DIMENSION, 0) AS LINEAS_SIN_DIMENSION,
    NVL(C.LINEAS_NIVEL_INVALIDO, 0) AS LINEAS_NIVEL_INVALIDO,
    NVL(C.LINEAS_VLOG_DUPLICADA, 0) AS LINEAS_VLOG_DUPLICADA,
    SYSDATE AS ORACLE_NOW
FROM VIAJES V
LEFT JOIN EXPEDICIONES E
  ON E.CEMPRESA = V.CEMPRESA
 AND E.CCENTDIS = V.CCENTDIS
 AND E.CNUVIAJE = V.CNUVIAJE
LEFT JOIN CARGA_EXPEDICION C
  ON C.CEMPRESA = E.CEMPRESA
 AND C.CNUVIAJE = E.CNUVIAJE
 AND C.CNUMEXPE = E.CNUMEXPE
ORDER BY
    CASE WHEN V.CNUANDEN IS NULL THEN 1 ELSE 0 END,
    V.CNUANDEN,
    NVL(V.FEAPERTU, V.FCREAREG) DESC,
    E.CNUMEXPE
"""


def _monitor_cache_lock() -> asyncio.Lock:
    global _monitor_lock
    if _monitor_lock is None:
        _monitor_lock = asyncio.Lock()
    return _monitor_lock


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _integer(value: Any) -> int:
    return int(round(_number(value)))


def _quality_for_expedition(row: dict[str, Any]) -> dict[str, Any]:
    bultos_calculados = _number(row.get("BULTOS_CALCULADOS"))
    bultos_f080 = _number(row.get("BULTOS_F080"))
    bultos_f035 = _number(row.get("BULTOS_F035"))

    details = {
        "pallets_sin_detalle": _integer(row.get("PALLETS_SIN_DETALLE")),
        "lineas_sin_vlog": _integer(row.get("LINEAS_SIN_VLOG")),
        "lineas_sin_dimension": _integer(row.get("LINEAS_SIN_DIMENSION")),
        "lineas_nivel_invalido": _integer(row.get("LINEAS_NIVEL_INVALIDO")),
        "lineas_vlog_duplicada": _integer(row.get("LINEAS_VLOG_DUPLICADA")),
        "diferencia_bultos_f080": round(bultos_calculados - bultos_f080, 3),
        "diferencia_bultos_f035": round(bultos_calculados - bultos_f035, 3),
    }
    structural_issues = sum(
        details[key]
        for key in (
            "pallets_sin_detalle",
            "lineas_sin_vlog",
            "lineas_sin_dimension",
            "lineas_nivel_invalido",
            "lineas_vlog_duplicada",
        )
    )
    reconciliation_issue = (
        abs(details["diferencia_bultos_f080"]) > 0.5
        or abs(details["diferencia_bultos_f035"]) > 0.5
    )
    return {
        "estado": "revisar" if structural_issues or reconciliation_issue else "ok",
        "incidencias": structural_issues + (1 if reconciliation_issue else 0),
        **details,
    }


def build_monitor_payload(rows: list[dict[str, Any]]) -> dict[str, Any]:
    trips: dict[tuple[str, str, str], dict[str, Any]] = {}
    oracle_now = ""

    for row in rows:
        company = _text(row.get("CEMPRESA"))
        center = _text(row.get("CCENTDIS"))
        trip_number = _text(row.get("CNUVIAJE"))
        if not trip_number:
            continue

        oracle_now = oracle_now or _text(row.get("ORACLE_NOW"))
        key = (company, center, trip_number)
        trip = trips.setdefault(
            key,
            {
                "empresa": company,
                "centro_distribucion": center,
                "viaje": trip_number,
                "hoja_ruta": _text(row.get("HOJARUTA")),
                "camion": _text(row.get("CAMIMATR")),
                "matricula": _text(row.get("CAMIMATR")),
                "anden": _text(row.get("CNUANDEN")),
                "capacidad_pallets": _integer(row.get("QPALMAXI")),
                "capacidad_volumen_dm3": round(_number(row.get("QVOLMAXI")), 3),
                "division_codigo": _text(row.get("CDIVISIO")),
                "division": _text(row.get("DIVISION")) or "OTROS",
                "cargador": _text(row.get("CARGADOR")),
                "fecha_creacion": _text(row.get("FCREAREG")),
                "fecha_apertura": _text(row.get("FEAPERTU")),
                "fecha_modificacion": _text(row.get("FMODIREG")),
                "bultos": 0,
                "volumen_dm3": 0.0,
                "pallets": 0,
                "lineas": 0,
                "calidad": {"estado": "ok", "incidencias": 0},
                "expediciones": [],
            },
        )

        expedition_number = _text(row.get("CNUMEXPE"))
        if not expedition_number:
            continue

        quality = _quality_for_expedition(row)
        expedition = {
            "expedicion": expedition_number,
            "estado": _text(row.get("CSITEXPE")),
            "fecha": _text(row.get("FECHA_EXPEDICION")),
            "pallets": _integer(row.get("PALLETS")),
            "lineas": _integer(row.get("LINEAS")),
            "bultos": _integer(row.get("BULTOS_CALCULADOS")),
            "volumen_dm3": round(_number(row.get("VOLUMEN_CALCULADO")), 3),
            "calidad": quality,
        }
        trip["expediciones"].append(expedition)
        trip["pallets"] += expedition["pallets"]
        trip["lineas"] += expedition["lineas"]
        trip["bultos"] += expedition["bultos"]
        trip["volumen_dm3"] += expedition["volumen_dm3"]
        trip["calidad"]["incidencias"] += quality["incidencias"]
        if quality["estado"] != "ok":
            trip["calidad"]["estado"] = "revisar"

    trip_list = list(trips.values())
    for trip in trip_list:
        trip["volumen_dm3"] = round(trip["volumen_dm3"], 3)
        capacity = _number(trip.get("capacidad_volumen_dm3"))
        trip["ocupacion_pct"] = (
            round((trip["volumen_dm3"] / capacity) * 100, 1)
            if capacity > 0
            else None
        )
        for expedition in trip["expediciones"]:
            expedition["ocupacion_pct"] = (
                round((expedition["volumen_dm3"] / capacity) * 100, 1)
                if capacity > 0
                else None
            )

    total_bultos = sum(trip["bultos"] for trip in trip_list)
    total_volume = round(sum(trip["volumen_dm3"] for trip in trip_list), 3)
    total_capacity = round(
        sum(
            _number(trip.get("capacidad_volumen_dm3"))
            for trip in trip_list
            if _number(trip.get("capacidad_volumen_dm3")) > 0
        ),
        3,
    )
    overall_occupancy = round((total_volume / total_capacity) * 100, 1) if total_capacity > 0 else None
    trips_with_issues = sum(1 for trip in trip_list if trip["calidad"]["estado"] != "ok")

    return {
        "source": "Oracle",
        "source_tables": ["F810VIAJ", "F811TRAI", "F035EXPE", "F080CPSA", "F081LPSA", "F054VLOG"],
        "refreshed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "oracle_now": oracle_now,
        "summary": {
            "viajes": len(trip_list),
            "bultos": total_bultos,
            "volumen_dm3": total_volume,
            "capacidad_volumen_dm3": total_capacity,
            "ocupacion_pct": overall_occupancy,
            "viajes_sin_capacidad": sum(
                1 for trip in trip_list if _number(trip.get("capacidad_volumen_dm3")) <= 0
            ),
            "viajes_con_observaciones": trips_with_issues,
        },
        "viajes": trip_list,
    }


def query_monitor_rows() -> list[dict[str, Any]]:
    return _query_productive_db_sql(
        QUERY_MONITOR_CARGAS,
        fecha_desde="",
        fecha_hasta="",
    )


async def load_monitor_payload(*, force: bool = False) -> dict[str, Any]:
    now = time.monotonic()
    cached = _monitor_cache.get("payload")
    if not force and cached is not None and now < float(_monitor_cache.get("expires_at") or 0):
        return cached

    async with _monitor_cache_lock():
        now = time.monotonic()
        cached = _monitor_cache.get("payload")
        if not force and cached is not None and now < float(_monitor_cache.get("expires_at") or 0):
            return cached

        try:
            rows = await asyncio.to_thread(query_monitor_rows)
        except Exception:
            if cached is not None:
                return {
                    **cached,
                    "stale": True,
                    "stale_served_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                }
            raise
        payload = build_monitor_payload(rows)
        payload["stale"] = False
        _monitor_cache["payload"] = payload
        _monitor_cache["expires_at"] = time.monotonic() + MONITOR_CACHE_SECONDS
        return payload


@router.get("/tablero")
async def monitor_cargas_tablero(
    force: bool = Query(False, description="Ignora el cache corto de proteccion a Oracle."),
) -> dict[str, Any]:
    try:
        return await load_monitor_payload(force=force)
    except Exception as exc:
        logger.exception("No se pudo consultar el monitor de cargas.")
        raise HTTPException(
            status_code=502,
            detail="No se pudo consultar Oracle para actualizar el monitor de cargas.",
        ) from exc
