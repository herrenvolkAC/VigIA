"""Base SQLite separada para historico de rendimiento online."""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite

from db.paths import resolve_db_path
from db.schema import DB_PATH


REND_HIST_DB_PATH = resolve_db_path(
    "RENDIMIENTO_HISTORICO_DB_PATH",
    "rendimiento_historico.db",
    Path(__file__).resolve().parent,
)

CREATE_RUNS = """
CREATE TABLE IF NOT EXISTS rend_hist_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    operacion       TEXT NOT NULL,
    dia_logistico   TEXT NOT NULL,
    fecha_desde     TEXT NOT NULL,
    fecha_hasta     TEXT NOT NULL,
    status          TEXT NOT NULL,
    movimientos     INTEGER DEFAULT 0,
    operaciones     INTEGER DEFAULT 0,
    error           TEXT,
    query_version   TEXT,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at      TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(operacion, dia_logistico)
);
"""

CREATE_LEGAJO_SECTOR = """
CREATE TABLE IF NOT EXISTS rend_hist_legajo_sector (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id                      INTEGER NOT NULL REFERENCES rend_hist_runs(id) ON DELETE CASCADE,
    operacion                   TEXT NOT NULL,
    dia_logistico               TEXT NOT NULL,
    division                    TEXT NOT NULL,
    sector                      TEXT NOT NULL,
    legajo                      TEXT NOT NULL,
    nombre                      TEXT,
    bultos                      REAL DEFAULT 0,
    segundos                    REAL DEFAULT 0,
    horas                       REAL DEFAULT 0,
    operaciones                 INTEGER DEFAULT 0,
    operaciones_abiertas        INTEGER DEFAULT 0,
    productividad_actual        REAL DEFAULT 0,
    productividad_esperada      REAL DEFAULT 0,
    productividad_esperada_turno REAL DEFAULT 0,
    bultos_esperados            REAL DEFAULT 0,
    cumplimiento_pct            REAL,
    estado                      TEXT,
    primer_movimiento           TEXT,
    ultimo_movimiento           TEXT,
    en_maestro                  INTEGER DEFAULT 0,
    requiere_maestro            INTEGER DEFAULT 0,
    created_at                  TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(run_id, division, sector, legajo)
);
"""

INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_rend_hist_runs_lookup ON rend_hist_runs(operacion, dia_logistico, status)",
    "CREATE INDEX IF NOT EXISTS idx_rend_hist_legajo_day ON rend_hist_legajo_sector(operacion, dia_logistico, legajo)",
    "CREATE INDEX IF NOT EXISTS idx_rend_hist_legajo_sector ON rend_hist_legajo_sector(division, sector, estado)",
]


async def init_rendimiento_historico_db() -> None:
    REND_HIST_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(REND_HIST_DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute(CREATE_RUNS)
        await db.execute(CREATE_LEGAJO_SECTOR)
        for stmt in INDEXES:
            await db.execute(stmt)
        await db.commit()


async def get_run(operacion: str, dia_logistico: str) -> dict[str, Any] | None:
    await init_rendimiento_historico_db()
    async with aiosqlite.connect(REND_HIST_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM rend_hist_runs WHERE operacion = ? AND dia_logistico = ?",
            (operacion, dia_logistico),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def save_day_cache(
    *,
    operacion: str,
    dia_logistico: str,
    fecha_desde: str,
    fecha_hasta: str,
    movimientos: int,
    operaciones: int,
    query_version: str,
    legajos: list[dict[str, Any]],
    status: str = "success",
    error: str | None = None,
    started_at: str | None = None,
) -> dict[str, Any]:
    await init_rendimiento_historico_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    started = started_at or now
    async with aiosqlite.connect(REND_HIST_DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute("BEGIN IMMEDIATE")
        await db.execute(
            """
            INSERT INTO rend_hist_runs (
                operacion, dia_logistico, fecha_desde, fecha_hasta, status,
                movimientos, operaciones, error, query_version, started_at, finished_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(operacion, dia_logistico) DO UPDATE SET
                fecha_desde = excluded.fecha_desde,
                fecha_hasta = excluded.fecha_hasta,
                status = excluded.status,
                movimientos = excluded.movimientos,
                operaciones = excluded.operaciones,
                error = excluded.error,
                query_version = excluded.query_version,
                started_at = excluded.started_at,
                finished_at = excluded.finished_at,
                updated_at = excluded.updated_at
            """,
            (
                operacion, dia_logistico, fecha_desde, fecha_hasta, status,
                movimientos, operaciones, error, query_version, started, now, now,
            ),
        )
        async with db.execute(
            "SELECT id FROM rend_hist_runs WHERE operacion = ? AND dia_logistico = ?",
            (operacion, dia_logistico),
        ) as cur:
            run_id = int((await cur.fetchone())[0])
        await db.execute("DELETE FROM rend_hist_legajo_sector WHERE run_id = ?", (run_id,))
        await db.executemany(
            """
            INSERT INTO rend_hist_legajo_sector (
                run_id, operacion, dia_logistico, division, sector, legajo, nombre,
                bultos, segundos, horas, operaciones, operaciones_abiertas,
                productividad_actual, productividad_esperada, productividad_esperada_turno,
                bultos_esperados, cumplimiento_pct, estado, primer_movimiento, ultimo_movimiento,
                en_maestro, requiere_maestro
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    run_id, operacion, dia_logistico, row.get("division"), row.get("sector"),
                    row.get("legajo"), row.get("nombre"), row.get("bultos"), row.get("segundos"),
                    row.get("horas"), row.get("operaciones"), row.get("operaciones_abiertas"),
                    row.get("productividad_actual"), row.get("productividad_esperada"),
                    row.get("productividad_esperada_turno"), row.get("bultos_esperados"),
                    row.get("cumplimiento_pct"), row.get("estado"), row.get("primer_movimiento"),
                    row.get("ultimo_movimiento"), int(bool(row.get("en_maestro"))),
                    int(bool(row.get("requiere_maestro"))),
                )
                for row in legajos
            ],
        )
        await db.commit()
    return {
        "operacion": operacion,
        "dia_logistico": dia_logistico,
        "status": status,
        "movimientos": movimientos,
        "operaciones": operaciones,
        "legajos_sector": len(legajos),
    }


def _estrato_antiguedad(days: float | None) -> str:
    if days is None:
        return "SIN_DATO"
    if days < 15:
        return "LT15"
    if days < 30:
        return "LT30"
    if days < 45:
        return "LT45"
    return "GT45"


def _calc_state(actual: float, expected: float) -> tuple[str, float | None]:
    if expected <= 0:
        return "none", None
    pct = actual / expected * 100
    if pct >= 95:
        return "ok", pct
    if pct >= 85:
        return "warn", pct
    return "bad", pct


async def get_analysis(
    *,
    operacion: str,
    fecha_desde: str,
    fecha_hasta: str,
    division: str = "",
    sector: str = "",
    sector_rrhh: str = "",
    funcion: str = "",
    estrato: str = "ALL",
) -> dict[str, Any]:
    await init_rendimiento_historico_db()
    where = [
        "h.operacion = ?",
        "h.dia_logistico >= ?",
        "h.dia_logistico <= ?",
    ]
    params: list[Any] = [operacion, fecha_desde, fecha_hasta]
    where_sql = " AND ".join(where)
    async with aiosqlite.connect(REND_HIST_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("ATTACH DATABASE ? AS vigia", (str(DB_PATH),))
        query = f"""
        WITH latest_legajero AS (
            SELECT *
            FROM (
                SELECT l.*,
                       ROW_NUMBER() OVER (
                           PARTITION BY l.legajo
                           ORDER BY b.imported_at DESC, l.batch_id DESC, l.id DESC
                       ) rn
                FROM vigia.rrhh_legajero l
                JOIN vigia.rrhh_import_batches b ON b.batch_id = l.batch_id
                WHERE b.status = 'complete'
            )
            WHERE rn = 1
        )
        SELECT h.*,
               COALESCE(NULLIF(TRIM(l.nombre), ''), h.nombre) nombre_legajero,
               COALESCE(NULLIF(TRIM(l.desc_sector_generico), ''), 'Sin sector') sector_rrhh,
               COALESCE(
                   (
                       SELECT fl.funcion_descripcion
                       FROM vigia.rrhh_funcion_cambio_detalle fd
                       JOIN vigia.rrhh_funcion_cambio_lotes fl ON fl.lote_id = fd.lote_id
                       WHERE fd.legajo = h.legajo
                         AND fd.estado = 'activo'
                         AND fl.cancelled_at IS NULL
                         AND fl.fecha_inicio <= h.dia_logistico
                         AND COALESCE(fl.fecha_fin, '9999-12-31') >= h.dia_logistico
                       ORDER BY fl.fecha_inicio DESC, fd.detalle_id DESC
                       LIMIT 1
                   ),
                   NULLIF(TRIM(l.desc_funcion), ''),
                   NULLIF(TRIM(l.desc_posicion), ''),
                   'Sin funcion'
               ) funcion,
               COALESCE(NULLIF(TRIM(l.desc_area_personal), ''), '') area_personal,
               l.fecha_ingreso,
               CASE
                   WHEN l.fecha_ingreso IS NOT NULL AND TRIM(l.fecha_ingreso) <> ''
                   THEN julianday(h.dia_logistico) - julianday(l.fecha_ingreso)
                   ELSE NULL
               END antiguedad_dias_calc
        FROM rend_hist_legajo_sector h
        LEFT JOIN latest_legajero l ON l.legajo = h.legajo
        WHERE {where_sql}
        """
        async with db.execute(query, params) as cur:
            base_rows = [dict(row) for row in await cur.fetchall()]
        await db.execute("DETACH DATABASE vigia")

    enriched = []
    for row in base_rows:
        days = row.get("antiguedad_dias_calc")
        days_num = float(days) if days is not None else None
        row["antiguedad_dias_calc"] = days_num
        row["estrato"] = _estrato_antiguedad(days_num)
        row["nombre"] = row.get("nombre_legajero") or row.get("nombre") or ""
        enriched.append(row)

    by_legajo: dict[str, dict[str, Any]] = {}
    by_detail: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in enriched:
        legajo = str(row.get("legajo") or "")
        leg = by_legajo.setdefault(legajo, {
            "legajo": legajo,
            "nombre": row.get("nombre") or "",
            "sector_rrhh": row.get("sector_rrhh") or "",
            "funcion": row.get("funcion") or "",
            "area_personal": row.get("area_personal") or "",
            "fecha_ingreso": row.get("fecha_ingreso"),
            "antiguedad_dias_calc": row.get("antiguedad_dias_calc"),
            "estrato": row.get("estrato"),
            "bultos": 0.0,
            "segundos": 0.0,
            "operaciones": 0,
            "bultos_esperados": 0.0,
            "divisiones": set(),
            "sectores": set(),
            "dias": set(),
            "sectores_rojo": 0,
            "sector_critico": "",
            "peor_cumplimiento": None,
            "ultimo_movimiento": row.get("ultimo_movimiento"),
        })
        leg["bultos"] += float(row.get("bultos") or 0)
        leg["segundos"] += float(row.get("segundos") or 0)
        leg["operaciones"] += int(row.get("operaciones") or 0)
        leg["bultos_esperados"] += float(row.get("bultos_esperados") or 0)
        leg["divisiones"].add(row.get("division"))
        leg["sectores"].add(row.get("sector"))
        leg["dias"].add(row.get("dia_logistico"))
        if row.get("estado") == "bad":
            leg["sectores_rojo"] += 1
        pct = row.get("cumplimiento_pct")
        if pct is not None and (leg["peor_cumplimiento"] is None or float(pct) < leg["peor_cumplimiento"]):
            leg["peor_cumplimiento"] = float(pct)
            leg["sector_critico"] = row.get("sector") or ""
        if row.get("ultimo_movimiento") and (not leg.get("ultimo_movimiento") or row["ultimo_movimiento"] > leg["ultimo_movimiento"]):
            leg["ultimo_movimiento"] = row["ultimo_movimiento"]

        detail_key = (legajo, row.get("division") or "", row.get("sector") or "")
        det = by_detail.setdefault(detail_key, {
            "legajo": legajo,
            "nombre": row.get("nombre") or "",
            "sector_rrhh": row.get("sector_rrhh") or "",
            "funcion": row.get("funcion") or "",
            "area_personal": row.get("area_personal") or "",
            "fecha_ingreso": row.get("fecha_ingreso"),
            "antiguedad_dias_calc": row.get("antiguedad_dias_calc"),
            "estrato": row.get("estrato"),
            "division": row.get("division"),
            "sector": row.get("sector"),
            "bultos": 0.0,
            "segundos": 0.0,
            "operaciones": 0,
            "bultos_esperados": 0.0,
            "dias": set(),
            "ultimo_movimiento": row.get("ultimo_movimiento"),
        })
        det["bultos"] += float(row.get("bultos") or 0)
        det["segundos"] += float(row.get("segundos") or 0)
        det["operaciones"] += int(row.get("operaciones") or 0)
        det["bultos_esperados"] += float(row.get("bultos_esperados") or 0)
        det["dias"].add(row.get("dia_logistico"))
        if row.get("ultimo_movimiento") and (not det.get("ultimo_movimiento") or row["ultimo_movimiento"] > det["ultimo_movimiento"]):
            det["ultimo_movimiento"] = row["ultimo_movimiento"]

    def finish(item: dict[str, Any]) -> dict[str, Any]:
        horas = item["segundos"] / 3600 if item["segundos"] else 0.0
        actual = item["bultos"] / horas if horas > 0 else 0.0
        expected = item["bultos_esperados"] / horas if horas > 0 else 0.0
        estado, cumplimiento = _calc_state(actual, expected)
        out = dict(item)
        out["horas"] = round(horas, 4)
        out["minutos"] = round(item["segundos"] / 60, 1)
        out["productividad_actual"] = round(actual, 2)
        out["productividad_esperada"] = round(expected, 2)
        out["cumplimiento_pct"] = round(cumplimiento, 1) if cumplimiento is not None else None
        out["estado"] = estado
        out["bultos"] = round(item["bultos"], 2)
        out["segundos"] = round(item["segundos"], 1)
        out["bultos_esperados"] = round(item["bultos_esperados"], 2)
        for key in ("divisiones", "sectores", "dias"):
            if isinstance(out.get(key), set):
                out[f"{key}_count"] = len(out[key])
                out[f"{key}_lista"] = ", ".join(sorted(str(v) for v in out[key] if v))
                out.pop(key, None)
        return out

    legajos = sorted((finish(item) for item in by_legajo.values()), key=lambda r: (r["estado"], r["cumplimiento_pct"] or 9999, r["legajo"]))
    detalle = sorted((finish(item) for item in by_detail.values()), key=lambda r: (r["legajo"], r["division"], r["sector"]))
    diario = sorted((finish(dict(row)) for row in enriched), key=lambda r: (r["dia_logistico"], r["legajo"], r["division"], r["sector"]))

    resumen = {
        "legajos": len(legajos),
        "bultos": round(sum(row["bultos"] for row in legajos), 2),
        "horas": round(sum(row["segundos"] for row in legajos) / 3600, 2),
        "sectores": len({(row.get("division"), row.get("sector")) for row in enriched}),
        "dias": len({row.get("dia_logistico") for row in enriched}),
    }
    resumen["productividad_actual"] = round(resumen["bultos"] / resumen["horas"], 2) if resumen["horas"] else 0.0

    filtros = {
        "divisiones": sorted({row.get("division") for row in base_rows if row.get("division")}),
        "sectores": sorted({row.get("sector") for row in base_rows if row.get("sector")}),
        "sectores_rrhh": sorted({row.get("sector_rrhh") for row in base_rows if row.get("sector_rrhh")}),
        "funciones": sorted({row.get("funcion") for row in base_rows if row.get("funcion")}),
    }
    return {
        "source": "rendimiento_historico_cache",
        "db_path": str(REND_HIST_DB_PATH),
        "operacion": operacion,
        "fecha_desde": fecha_desde,
        "fecha_hasta": fecha_hasta,
        "resumen": resumen,
        "filtros": filtros,
        "legajos": legajos,
        "detalle": detalle,
        "diario": diario,
    }
