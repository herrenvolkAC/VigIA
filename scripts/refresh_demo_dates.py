"""
VigIA - Refrescar fechas de demo

Reasigna todas las fechas distintas encontradas en las tablas operativas para que:
- la fecha mas nueva pase por default a manana
- la anterior pase a ser ayer
- y asi sucesivamente

Tambien ajusta los campos timestamp/datetime para conservar la hora original
pero con la nueva fecha.

Uso:
    python scripts/refresh_demo_dates.py
    python scripts/refresh_demo_dates.py --dry-run
    python scripts/refresh_demo_dates.py --day-offset 0
    python scripts/refresh_demo_dates.py --db C:\\ruta\\vigia.db
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path


DEFAULT_TABLES = [
    "picks_operario",
    "errores_operario",
    "pausas_operario",
    "ausentismo_operario",
    "turnos",
]

TIMESTAMP_COLUMNS = {
    "picks_operario": ["timestamp"],
    "errores_operario": ["timestamp"],
    "pausas_operario": ["timestamp_inicio", "timestamp_fin"],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresca fechas de la BD demo.")
    parser.add_argument(
        "--db",
        default=str(Path(__file__).resolve().parent.parent / "vigia.db"),
        help="Ruta al archivo SQLite a actualizar.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Muestra el plan y el resumen sin escribir cambios.",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="No genera copia .bak antes de actualizar.",
    )
    parser.add_argument(
        "--day-offset",
        type=int,
        default=1,
        help="Desplazamiento del destino base respecto de hoy. Default: 1 (manana).",
    )
    return parser.parse_args()


def get_distinct_dates(conn: sqlite3.Connection, tables: list[str]) -> list[str]:
    fechas: set[str] = set()
    for table in tables:
        rows = conn.execute(f"SELECT DISTINCT fecha FROM {table} WHERE fecha IS NOT NULL").fetchall()
        fechas.update(row[0] for row in rows if row[0])
    return sorted(fechas)


def build_date_mapping(source_dates: list[str], target_today: date) -> dict[str, str]:
    ordered_desc = sorted(source_dates, reverse=True)
    mapping: dict[str, str] = {}
    for idx, old_date in enumerate(ordered_desc):
        mapping[old_date] = (target_today - timedelta(days=idx)).isoformat()
    return mapping


def backup_database(db_path: Path) -> Path:
    backup_path = db_path.with_suffix(db_path.suffix + f".bak_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    shutil.copy2(db_path, backup_path)
    return backup_path


def update_table_dates(
    conn: sqlite3.Connection,
    table: str,
    mapping: dict[str, str],
    dry_run: bool,
) -> dict[str, int]:
    summary = {"rows_fecha": 0, "rows_timestamp": 0}

    for old_date, new_date in mapping.items():
        rows_fecha = conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE fecha = ?",
            (old_date,),
        ).fetchone()[0]
        summary["rows_fecha"] += rows_fecha

        if not dry_run and rows_fecha:
            conn.execute(
                f"UPDATE {table} SET fecha = ? WHERE fecha = ?",
                (new_date, old_date),
            )

        for column in TIMESTAMP_COLUMNS.get(table, []):
            rows_ts = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {column} IS NOT NULL AND substr({column}, 1, 10) = ?",
                (old_date,),
            ).fetchone()[0]
            summary["rows_timestamp"] += rows_ts

            if not dry_run and rows_ts:
                conn.execute(
                    f"""
                    UPDATE {table}
                    SET {column} = ? || substr({column}, 11)
                    WHERE {column} IS NOT NULL
                      AND substr({column}, 1, 10) = ?
                    """,
                    (new_date, old_date),
                )

    return summary


def collect_range(conn: sqlite3.Connection, tables: list[str]) -> tuple[str | None, str | None]:
    min_date = None
    max_date = None
    for table in tables:
        current_min, current_max = conn.execute(
            f"SELECT MIN(fecha), MAX(fecha) FROM {table}"
        ).fetchone()
        if current_min and (min_date is None or current_min < min_date):
            min_date = current_min
        if current_max and (max_date is None or current_max > max_date):
            max_date = current_max
    return min_date, max_date


def main() -> int:
    args = parse_args()
    db_path = Path(args.db).resolve()

    if not db_path.exists():
        raise SystemExit(f"No existe la BD: {db_path}")

    with sqlite3.connect(db_path) as conn:
        source_dates = get_distinct_dates(conn, DEFAULT_TABLES)
        if not source_dates:
            print("No se encontraron fechas para mover.")
            return 0

        old_min, old_max = collect_range(conn, DEFAULT_TABLES)
        target_base = date.today() + timedelta(days=args.day_offset)
        mapping = build_date_mapping(source_dates, target_base)
        new_dates = sorted(mapping.values())

        print("VigIA - Refresh demo dates")
        print(f"BD: {db_path}")
        print(f"Modo: {'DRY RUN' if args.dry_run else 'ACTUALIZACION REAL'}")
        print(f"Fecha destino mas nueva: {target_base.isoformat()} (offset {args.day_offset:+d})")
        print(f"Fechas distintas a mover: {len(mapping)}")
        print(f"Rango original: {old_min} -> {old_max}")
        print(f"Rango nuevo:    {new_dates[0]} -> {new_dates[-1]}")
        print("")
        print("Primeras reasignaciones:")
        for old_date in sorted(mapping, reverse=True)[:10]:
            print(f"  {old_date} -> {mapping[old_date]}")
        if len(mapping) > 10:
            print("  ...")

        backup_path = None
        if not args.dry_run and not args.no_backup:
            backup_path = backup_database(db_path)

        table_summaries: dict[str, dict[str, int]] = {}
        for table in DEFAULT_TABLES:
            table_summaries[table] = update_table_dates(conn, table, mapping, args.dry_run)

        if args.dry_run:
            conn.rollback()
        else:
            conn.commit()

        print("")
        print("Resumen por tabla:")
        total_rows_fecha = 0
        total_rows_timestamp = 0
        for table, stats in table_summaries.items():
            total_rows_fecha += stats["rows_fecha"]
            total_rows_timestamp += stats["rows_timestamp"]
            print(
                f"  {table}: "
                f"{stats['rows_fecha']} filas con fecha, "
                f"{stats['rows_timestamp']} timestamps ajustados"
            )

        print("")
        print("Resumen final:")
        print(f"  Fechas movidas: {len(mapping)}")
        print(f"  Rango viejo: {old_min} -> {old_max}")
        print(f"  Rango nuevo: {new_dates[0]} -> {new_dates[-1]}")
        print(f"  Filas actualizadas por fecha: {total_rows_fecha}")
        print(f"  Timestamps ajustados: {total_rows_timestamp}")
        if backup_path:
            print(f"  Backup: {backup_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
