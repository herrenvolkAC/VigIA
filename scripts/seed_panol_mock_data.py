from __future__ import annotations

import argparse
import asyncio
import random
import sqlite3
from datetime import date, datetime, time, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

import sys

sys.path.insert(0, str(ROOT))

from db.panol_insumos import PANOL_DB_PATH, init_panol_db


ARTICLES = [
    ("840001", "Film stretch 50 cm", "Embalaje", "ROL", "Armado\nDespacho", 120),
    ("840002", "Cinta adhesiva transparente", "Embalaje", "UN", "Armado\nPicking", 180),
    ("840003", "Etiqueta termica 100x150", "Etiquetas", "ROL", "Despacho\nRecepcion", 90),
    ("840004", "Precinto numerado rojo", "Seguridad", "UN", "Despacho\nRechazo", 450),
    ("840005", "Bolsa ecommerce mediana", "Embalaje", "UN", "Envios a Domicilio", 800),
    ("840006", "Bolsa ecommerce grande", "Embalaje", "UN", "Envios a Domicilio", 650),
    ("840007", "Caja carton chica", "Embalaje", "UN", "Armado", 300),
    ("840008", "Caja carton mediana", "Embalaje", "UN", "Armado", 260),
    ("840009", "Zuncho plastico 12 mm", "Embalaje", "ROL", "Despacho", 70),
    ("840010", "Guante nitrilo talle L", "EPP", "CAJ", "Recepcion\nRefrigerados", 55),
    ("840011", "Barbijo descartable", "EPP", "CAJ", "Recepcion\nSecos", 45),
    ("840012", "Hoja separadora pallet", "Embalaje", "UN", "Picking", 350),
    ("840013", "Etiqueta frio", "Etiquetas", "ROL", "Refrigerados", 65),
    ("840014", "Tarima descartable", "Logistica", "UN", "Sucursales", 40),
]

SECTOR_CODES = [
    "Envios a Domicilio",
    "Noa",
    "Refrigerados",
    "Secos",
    "Sector 126",
    "Sucursales",
]

USERS = ["panol.admin", "operador.ado", "supervisor.turno", "solicitante.sector"]
ORDER_USERS = [
    "admin",
    "acucci",
    "envios.user",
    "noa.user",
    "refrig.user",
    "secos.user",
    "sector126.user",
]


def dt_at(day: date, hour: int, minute: int = 0) -> str:
    return datetime.combine(day, time(hour, minute)).strftime("%Y-%m-%d %H:%M:%S")


def turn_for_hour(hour: int) -> str:
    if 6 <= hour < 14:
        return "MANANA"
    if 14 <= hour < 22:
        return "TARDE"
    return "NOCHE"


def ensure_schema() -> None:
    asyncio.run(init_panol_db())


def scalar(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> float:
    value = conn.execute(sql, params).fetchone()[0]
    return float(value or 0)


def upsert_articles(conn: sqlite3.Connection) -> dict[str, int]:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for codigo, descripcion, categoria, unidad, uso, minimo in ARTICLES:
        conn.execute(
            """
            INSERT INTO articulos
                (codigo, descripcion, categoria, unidad, uso, stock_minimo, activo, creado_en, actualizado_en)
            VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
            ON CONFLICT(codigo) DO UPDATE SET
                descripcion = excluded.descripcion,
                categoria = excluded.categoria,
                unidad = excluded.unidad,
                uso = excluded.uso,
                stock_minimo = excluded.stock_minimo,
                activo = 1,
                actualizado_en = excluded.actualizado_en
            """,
            (codigo, descripcion, categoria, unidad, uso, minimo, now, now),
        )
    return {
        codigo: int(row_id)
        for codigo, row_id in conn.execute("SELECT codigo, id FROM articulos WHERE codigo LIKE '8400%'")
    }


def ensure_locations(conn: sqlite3.Connection) -> dict[str, int]:
    locations = ["JAULA", "OFICINA_ADO", *SECTOR_CODES]
    for code in locations:
        conn.execute(
            """
            INSERT INTO ubicaciones (codigo, descripcion, activo)
            VALUES (?, ?, 1)
            ON CONFLICT(codigo) DO UPDATE SET descripcion = excluded.descripcion, activo = 1
            """,
            (code, code),
        )
    return {code: int(row_id) for code, row_id in conn.execute("SELECT codigo, id FROM ubicaciones WHERE activo = 1")}


def clear_operational_data(conn: sqlite3.Connection) -> None:
    for table in [
        "pedidos_insumos_items",
        "pedidos_insumos",
        "movimientos",
        "stock_cd_importado",
        "consumos_calculados",
        "inventario_turno",
        "produccion_movimientos",
    ]:
        conn.execute(f"DELETE FROM {table}")
    conn.execute(
        """
        DELETE FROM sqlite_sequence
        WHERE name IN (
            'pedidos_insumos_items', 'pedidos_insumos', 'movimientos', 'stock_cd_importado',
            'inventario_turno', 'consumos_calculados', 'produccion_movimientos'
        )
        """
    )


def seed_stock(conn: sqlite3.Connection, article_ids: dict[str, int], location_ids: dict[str, int], start: date, end: date) -> None:
    jaula_id = location_ids["JAULA"]
    oficina_id = location_ids["OFICINA_ADO"]
    rng = random.Random(4201)

    for idx, (codigo, *_rest) in enumerate(ARTICLES):
        article_id = article_ids[codigo]
        initial = rng.randint(900, 2600) + idx * 35
        conn.execute(
            """
            INSERT INTO movimientos
                (articulo_id, tipo, ubicacion_destino_id, cantidad, motivo, observacion, usuario, fecha_hora)
            VALUES (?, 'ALTA', ?, ?, 'STOCK_INICIAL_MOCK', 'Carga inicial mock ultimos 3 meses', ?, ?)
            """,
            (article_id, jaula_id, initial, USERS[0], dt_at(start, 7, 15)),
        )

        stock_cd = initial + rng.randint(350, 1400)
        for week in range(0, 91, 7):
            day = min(start + timedelta(days=week), end)
            drift = rng.randint(-120, 180)
            conn.execute(
                """
                INSERT INTO stock_cd_importado
                    (articulo_id, stock_cd, fecha_reporte, archivo_origen, usuario_importacion, fecha_importacion)
                VALUES (?, ?, ?, 'MOCK_REP_STK_CD_UNID', ?, ?)
                """,
                (article_id, max(0, stock_cd + drift), day.isoformat(), USERS[0], dt_at(day, 6, 45)),
            )

    office_balance = {article_ids[codigo]: 0.0 for codigo, *_ in ARTICLES}
    for day_offset in range((end - start).days + 1):
        day = start + timedelta(days=day_offset)
        is_workday = day.weekday() < 6
        for idx, (codigo, *_rest) in enumerate(ARTICLES):
            article_id = article_ids[codigo]
            if is_workday and (day_offset + idx) % 3 == 0:
                qty = rng.randint(18, 95)
                conn.execute(
                    """
                    INSERT INTO movimientos
                        (articulo_id, tipo, ubicacion_origen_id, ubicacion_destino_id, cantidad,
                         motivo, observacion, usuario, fecha_hora)
                    VALUES (?, 'TRANSFERENCIA', ?, ?, ?, 'REPOSICION_ADO', 'Reposicion mock Jaula a Oficina ADO', ?, ?)
                    """,
                    (article_id, jaula_id, oficina_id, qty, USERS[1], dt_at(day, 8 + idx % 3, 10)),
                )
                office_balance[article_id] += qty
            if is_workday and office_balance[article_id] > 20 and (day_offset + idx) % 2 == 0:
                qty = min(office_balance[article_id] * 0.45, rng.randint(8, 55))
                conn.execute(
                    """
                    INSERT INTO movimientos
                        (articulo_id, tipo, ubicacion_origen_id, cantidad, motivo, observacion, usuario, fecha_hora)
                    VALUES (?, 'BAJA', ?, ?, 'CONSUMO_OPERATIVO', 'Consumo mock por turno', ?, ?)
                    """,
                    (article_id, oficina_id, round(qty, 2), USERS[2], dt_at(day, 16 + idx % 4, 20)),
                )
                office_balance[article_id] -= qty

        if day.weekday() in {0, 2, 4} or day == end:
            for idx, (codigo, *_rest) in enumerate(ARTICLES):
                article_id = article_ids[codigo]
                physical = max(0, office_balance[article_id] + rng.randint(-4, 6))
                stock_initial = max(0, physical + rng.randint(5, 35))
                ingresos = rng.randint(0, 28)
                consumo = max(0, stock_initial + ingresos - physical)
                cur = conn.execute(
                    """
                    INSERT INTO inventario_turno
                        (articulo_id, ubicacion_id, turno, fecha, stock_fisico, usuario, fecha_hora, observacion)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'Inventario mock Oficina ADO')
                    """,
                    (
                        article_id,
                        oficina_id,
                        turn_for_hour(21),
                        day.isoformat(),
                        round(physical, 2),
                        USERS[1],
                        dt_at(day, 21, 30),
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO consumos_calculados
                        (articulo_id, fecha, turno, stock_inicial, ingresos_turno, stock_final,
                         consumo_calculado, usuario, fecha_hora, inventario_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        article_id,
                        day.isoformat(),
                        "TARDE",
                        round(stock_initial, 2),
                        round(ingresos, 2),
                        round(physical, 2),
                        round(consumo, 2),
                        USERS[1],
                        dt_at(day, 21, 31),
                        cur.lastrowid,
                    ),
                )
                office_balance[article_id] = physical


def seed_production(conn: sqlite3.Connection, article_ids: dict[str, int], location_ids: dict[str, int], start: date, end: date) -> None:
    rng = random.Random(7844)
    production_codes = ["840003", "840005", "840006", "840007", "840008", "840012", "840013", "840014"]
    sectors = [location_ids[code] for code in SECTOR_CODES if code in location_ids]
    produced_balance = {article_ids[code]: 0.0 for code in production_codes}

    for day_offset in range((end - start).days + 1):
        day = start + timedelta(days=day_offset)
        if day.weekday() == 6:
            continue
        for idx, code in enumerate(production_codes):
            article_id = article_ids[code]
            if (day_offset + idx) % 2 == 0:
                qty = rng.randint(35, 170)
                hour = [7, 15, 23][(day_offset + idx) % 3]
                conn.execute(
                    """
                    INSERT INTO produccion_movimientos
                        (articulo_id, tipo, cantidad, turno, observacion, usuario, fecha_hora)
                    VALUES (?, 'PRODUCCION', ?, ?, 'Alta mock de produccion', ?, ?)
                    """,
                    (article_id, qty, turn_for_hour(hour), USERS[1], dt_at(day, hour, 40)),
                )
                produced_balance[article_id] += qty
            if produced_balance[article_id] > 25 and (day_offset + idx) % 3 == 0:
                qty = min(produced_balance[article_id] * 0.55, rng.randint(18, 110))
                dest = sectors[(day_offset + idx) % len(sectors)]
                hour = [10, 18, 1][(day_offset + idx) % 3]
                conn.execute(
                    """
                    INSERT INTO produccion_movimientos
                        (articulo_id, tipo, ubicacion_destino_id, cantidad, turno, observacion, usuario, fecha_hora)
                    VALUES (?, 'ENTREGA', ?, ?, ?, 'Entrega mock a sector', ?, ?)
                    """,
                    (article_id, dest, round(qty, 2), turn_for_hour(hour), USERS[2], dt_at(day, hour, 5)),
                )
                produced_balance[article_id] -= qty


def seed_orders(conn: sqlite3.Connection, article_ids: dict[str, int], location_ids: dict[str, int], start: date, end: date) -> None:
    rng = random.Random(9917)
    all_article_ids = list(article_ids.values())
    sectors = [location_ids[code] for code in SECTOR_CODES if code in location_ids]
    oficina_id = location_ids["OFICINA_ADO"]

    for day_offset in range((end - start).days + 1):
        day = start + timedelta(days=day_offset)
        if day.weekday() == 6:
            continue
        orders_today = 1 + (1 if day_offset % 4 == 0 else 0) + (1 if day_offset % 11 == 0 else 0)
        for n in range(orders_today):
            is_recent = (end - day).days <= 8
            estado = rng.choices(
                ["PENDIENTE", "CONFIRMADO", "CONFIRMADO_PARCIAL", "CANCELADO"],
                weights=[28 if is_recent else 4, 55, 13, 4],
                k=1,
            )[0]
            requested_at = dt_at(day, 9 + (n * 3) % 9, rng.choice([5, 20, 35, 50]))
            confirmed_at = None if estado == "PENDIENTE" else dt_at(min(day + timedelta(days=rng.randint(0, 2)), end), 15 + n, 15)
            cur = conn.execute(
                """
                INSERT INTO pedidos_insumos
                    (sector_id, estado, usuario_solicita, fecha_solicitud, observacion_solicitud,
                     usuario_confirma, fecha_confirmacion, observacion_confirmacion)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sectors[(day_offset + n) % len(sectors)],
                    estado,
                    ORDER_USERS[(day_offset + n) % len(ORDER_USERS)],
                    requested_at,
                    "Pedido mock generado para tablero",
                    USERS[1] if confirmed_at else None,
                    confirmed_at,
                    "Confirmacion mock" if confirmed_at else None,
                ),
            )
            pedido_id = int(cur.lastrowid)
            for article_id in rng.sample(all_article_ids, rng.randint(1, 4)):
                req_insumo = float(rng.randint(0, 42))
                req_prod = float(rng.randint(0, 32)) if article_id % 2 == 0 else 0.0
                if req_insumo <= 0 and req_prod <= 0:
                    req_insumo = float(rng.randint(6, 24))
                if estado == "PENDIENTE":
                    conf_insumo = conf_prod = 0.0
                elif estado == "CANCELADO":
                    conf_insumo = conf_prod = 0.0
                elif estado == "CONFIRMADO_PARCIAL":
                    conf_insumo = round(req_insumo * rng.uniform(0.35, 0.8), 2)
                    conf_prod = round(req_prod * rng.uniform(0.35, 0.8), 2)
                else:
                    conf_insumo = req_insumo
                    conf_prod = req_prod
                conn.execute(
                    """
                    INSERT INTO pedidos_insumos_items
                        (pedido_id, articulo_id, cantidad_insumo_solicitada, cantidad_produccion_solicitada,
                         cantidad_insumo_confirmada, cantidad_produccion_confirmada, ubicacion_origen_insumo_id, uso_entrega)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        pedido_id,
                        article_id,
                        req_insumo,
                        req_prod,
                        conf_insumo,
                        conf_prod,
                        oficina_id if conf_insumo > 0 else None,
                        "Armado" if conf_insumo > 0 or conf_prod > 0 else "",
                    ),
                )


def verify(conn: sqlite3.Connection, start: date, end: date) -> dict[str, int | str]:
    tables = [
        "articulos",
        "movimientos",
        "stock_cd_importado",
        "inventario_turno",
        "consumos_calculados",
        "produccion_movimientos",
        "pedidos_insumos",
        "pedidos_insumos_items",
    ]
    result: dict[str, int | str] = {
        "fecha_desde": start.isoformat(),
        "fecha_hasta": end.isoformat(),
    }
    for table in tables:
        result[table] = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    result["pedidos_pendientes"] = int(
        conn.execute("SELECT COUNT(*) FROM pedidos_insumos WHERE estado = 'PENDIENTE'").fetchone()[0]
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Genera datos mock para Panol Insumos.")
    parser.add_argument("--days", type=int, default=90, help="Cantidad de dias hacia atras a generar.")
    parser.add_argument("--end-date", default=date.today().isoformat(), help="Fecha final YYYY-MM-DD.")
    args = parser.parse_args()

    end = datetime.strptime(args.end_date, "%Y-%m-%d").date()
    start = end - timedelta(days=max(args.days, 1) - 1)

    ensure_schema()
    conn = sqlite3.connect(PANOL_DB_PATH)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN")
        clear_operational_data(conn)
        article_ids = upsert_articles(conn)
        location_ids = ensure_locations(conn)
        seed_stock(conn, article_ids, location_ids, start, end)
        seed_production(conn, article_ids, location_ids, start, end)
        seed_orders(conn, article_ids, location_ids, start, end)
        conn.commit()
        summary = verify(conn, start, end)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(f"Base: {PANOL_DB_PATH}")
    for key, value in summary.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
