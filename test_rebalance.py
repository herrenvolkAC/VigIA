"""
Test rápido del endpoint POST /api/rebalance/simular
"""
import asyncio
import aiosqlite
from pathlib import Path
import json

DB_PATH = Path(__file__).parent / "vigia.db"


async def test_rebalance():
    """Simular movimiento de operarios"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        # Simulación: mover OP_00045 (María López) y OP_00087 (Carmen Martín) de Secos a NOA
        operarios_mover = ["OP_00045", "OP_00087"]
        zona_origen = "Secos"
        zona_destino = "NOA"

        # 1. Obtener estándares
        cursor = await db.execute("""
            SELECT bultos_por_hora FROM estandares_sector WHERE sector = ?
        """, (zona_origen,))
        std_origen = await cursor.fetchone()
        est_origen = std_origen['bultos_por_hora'] if std_origen else 250

        cursor = await db.execute("""
            SELECT bultos_por_hora FROM estandares_sector WHERE sector = ?
        """, (zona_destino,))
        std_destino = await cursor.fetchone()
        est_destino = std_destino['bultos_por_hora'] if std_destino else 60

        print(f"\n{'='*60}")
        print("TEST: POST /api/rebalance/simular")
        print(f"{'='*60}\n")

        print(f"Movimiento: {zona_origen} (est: {est_origen} bul/h) -> {zona_destino} (est: {est_destino} bul/h)")
        print(f"Operarios: {operarios_mover}\n")

        # 2. Calcular impacto
        bultos_perdidos = 0
        operarios_info = []

        for op_id in operarios_mover:
            cursor = await db.execute("""
                SELECT o.nombre, a.bultos_reales, a.productividad
                FROM asignaciones_ola a
                JOIN operarios o ON a.operario_id = o.operario_id
                WHERE a.ola_id = 'OLA_2_TARDE_20_04' AND a.operario_id = ?
            """, (op_id,))
            op_data = await cursor.fetchone()

            if op_data:
                bultos_perdidos += op_data['bultos_reales']
                operarios_info.append({
                    "id": op_id,
                    "nombre": op_data['nombre'],
                    "bultos": op_data['bultos_reales'],
                    "productividad": op_data['productividad']
                })

        print("Operarios a mover:")
        for op in operarios_info:
            print(f"  - {op['nombre']}: {op['bultos']} bultos ({op['productividad']} bul/h)")

        bultos_ganados = len(operarios_mover) * (est_destino / 60 * 60)
        impacto_neto = bultos_ganados - bultos_perdidos

        print(f"\nImpacto:")
        print(f"  Bultos perdidos (Secos): {bultos_perdidos}")
        print(f"  Bultos ganados (NOA): {int(bultos_ganados)}")
        print(f"  Impacto neto: {int(impacto_neto)}")

        if impacto_neto < 0:
            recomendacion = "NO HACER"
            print(f"\nRecomendación: {recomendacion} (pérdida neta)")
        elif impacto_neto == 0:
            recomendacion = "NEUTRAL"
            print(f"\nRecomendación: {recomendacion}")
        else:
            recomendacion = "HACER"
            print(f"\nRecomendación: {recomendacion} (ganancia neta)")

        print(f"{'='*60}\n")


if __name__ == "__main__":
    asyncio.run(test_rebalance())
