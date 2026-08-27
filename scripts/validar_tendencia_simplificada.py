"""Valida cobertura, unicidad y consistencia del cache mensual de productividad."""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import date
from pathlib import Path

import aiosqlite

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from db.analisis_productividad import ANALISIS_PRODUCTIVIDAD_DB_PATH


async def main() -> None:
    async with aiosqlite.connect(ANALISIS_PRODUCTIVIDAD_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        duplicate = await (await db.execute(
            """SELECT operacion, grupo_productivo, mes, COUNT(*) AS cantidad
               FROM ap_tendencia_mensual
               WHERE operacion IN ('CARGA','PICKING')
               GROUP BY operacion, grupo_productivo, mes HAVING COUNT(*) > 1"""
        )).fetchall()
        rows = await (await db.execute(
            """SELECT operacion, grupo_productivo, mes, payload_json
               FROM ap_tendencia_mensual
               WHERE operacion IN ('CARGA','PICKING') AND grupo_productivo=0
               ORDER BY operacion, mes"""
        )).fetchall()
    start_year, start_month = 2024, 1
    end_year, end_month = date.today().year, date.today().month
    months = []
    year, month = start_year, start_month
    while (year, month) <= (end_year, end_month):
        months.append(year * 100 + month)
        month += 1
        if month == 13:
            year, month = year + 1, 1
    expected = {(op, month) for op in ('CARGA', 'PICKING') for month in months}
    actual = {(row['operacion'], int(row['mes'])) for row in rows}
    missing = sorted(expected - actual)
    invalid = []
    for row in rows:
        item = json.loads(row['payload_json'])
        for key in ('prod_real', 'eq_sector', 'eq_consol', 'eq_traslado', 'produccion_total', 'productividad', 'legajos'):
            value = item.get(key)
            if value is not None and (not isinstance(value, (int, float)) or value < 0):
                invalid.append((row['operacion'], row['mes'], key, value))
    print(f"DB={ANALISIS_PRODUCTIVIDAD_DB_PATH}")
    print(f"filas={len(rows)} duplicados={len(duplicate)} faltantes={len(missing)} invalidos={len(invalid)}")
    if duplicate:
        print('DUPLICADOS:', [dict(row) for row in duplicate])
    if missing:
        print('FALTANTES:', missing)
    if invalid:
        print('INVALIDOS:', invalid[:20])
    if duplicate or missing or invalid:
        raise SystemExit(1)
    print('VALIDACION=OK')


if __name__ == '__main__':
    asyncio.run(main())
