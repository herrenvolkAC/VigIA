"""
Script para generar alertas de prueba
Inserta errores en la BD para que ciertos operarios disparen alertas
"""

import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "vigia.db"

def generar_alertas_test():
    """Genera datos de prueba para alertas"""
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()

    # Operarios de prueba
    operarios_test = [
        ("OP_00045", "Secos"),
        ("OP_00067", "Secos"),
        ("OP_00089", "Repacking")
    ]

    print("Generando alertas de prueba...")
    now = datetime.now()
    today = str(now.date())
    timestamp = now.isoformat()

    for operario_id, sector in operarios_test:
        # Insertar 10 picks con estado 'error' para este operario HOY
        for i in range(10):
            c.execute("""
                INSERT INTO picks_operario
                (pick_id, fecha, timestamp, turno_id, ola_id, operario_id, sector, sku, cantidad_bultos, peso_kg, tiempo_segundos, estado)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                f"{operario_id}_error_{i}",
                today,
                timestamp,
                "TURNO_20240101_1",
                "OLA_2_TARDE_20_04",
                operario_id,
                sector,
                "SKU000904",
                1,
                5.1,
                30,
                "error"  # ← Estado error
            ))

        print(f"[OK] {operario_id}: +10 errores insertados")

    conn.commit()

    # Verificar
    print("\n[INFO] Verificando...")
    for operario_id, _ in operarios_test:
        c.execute("""
            SELECT
                COUNT(*) as picks,
                COUNT(CASE WHEN estado = 'error' THEN 1 END) as errores
            FROM picks_operario
            WHERE operario_id = ? AND fecha >= DATE('now')
        """, (operario_id,))

        picks, errores = c.fetchone()
        tasa_error = (errores / picks * 100) if picks > 0 else 0
        print(f"{operario_id}: {picks} picks, {errores} errores, tasa: {tasa_error:.1f}%")

    conn.close()
    print("\n[OK] Alertas de prueba generadas!")
    print("[INFO] Recarga el dashboard: http://localhost:8000/config_y_recomendaciones")
    print("[INFO] Tab 'Alertas' deberia mostrar operarios con tasa de error alta")

if __name__ == "__main__":
    generar_alertas_test()
