"""Configura Refrigerados/Armador (otras cámaras) para aprox. +15%.

Actualiza únicamente parámetros y umbrales individuales derivados. No recalcula
los caches; la auditoría conserva los valores anteriores para revisión.
"""
from __future__ import annotations

from datetime import datetime
import json
import math
from pathlib import Path
import sqlite3


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "datos" / "laboratorio_premios.db"
PROFILE = ("CD-REFRIGERADOS", "ARMADOR", "ARMADO", "2,4")
NEW_OBJECTIVE = 820.0
NEW_GROUP_AWARD = 1900.0
PERCENTAGES = (10.0, 5.0, 10.0, 15.0, 20.0)


def thresholds(base: float) -> list[tuple[int, int, int, float]]:
    value = float(base)
    starts: list[int] = []
    for percentage in PERCENTAGES:
        value *= 1 + percentage / 100
        starts.append(math.ceil(value - 1e-9))
    return [
        (level, starts[level - 1], starts[level] if level < 5 else 0,
         PERCENTAGES[level - 1])
        for level in range(1, 6)
    ]


def main() -> None:
    sector, function, operation, division = PROFILE
    execution = datetime.now().astimezone().isoformat(timespec="seconds")
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    try:
        db.execute("BEGIN IMMEDIATE")
        params = [dict(row) for row in db.execute(
            """SELECT * FROM lab_parametro_grupal
               WHERE activo=1 AND sector=? AND funcion_legajero=?
                 AND UPPER(TRIM(operacion_medible))=? AND COALESCE(division_madre,'')=?
               ORDER BY CAST(turno AS INTEGER),turno""",
            (sector, function, operation, division),
        )]
        scales = [dict(row) for row in db.execute(
            """SELECT * FROM lab_escala_individual_grupal
               WHERE activo=1 AND sector=? AND funcion_legajero=?
                 AND UPPER(TRIM(operacion_medible))=? AND COALESCE(division_madre,'')=?
               ORDER BY CAST(turno AS INTEGER),turno,nivel""",
            (sector, function, operation, division),
        )]
        if len(params) != 3 or len(scales) != 15:
            raise RuntimeError(f"Perfil inesperado: parámetros={len(params)}, escalas={len(scales)}")
        if {str(row["turno"]) for row in params} != {"1", "2", "3"}:
            raise RuntimeError("Los turnos activos no son 1, 2 y 3.")
        for level in range(1, 6):
            level_rows = [row for row in scales if int(row["nivel"]) == level]
            if len(level_rows) != 3 or len({float(row["premio"]) for row in level_rows}) != 1:
                raise RuntimeError(f"El monto del nivel {level} no es común a los tres turnos.")
        if any(float(row["factor_ausentismo"]) != 5 for row in params):
            raise RuntimeError("Cambió el factor de ausentismo; revisar el escenario antes de aplicarlo.")

        audit_payload = json.dumps(
            {"parametros_antes": params, "escalas_antes": scales,
             "objetivo_nuevo": NEW_OBJECTIVE, "premio_grupal_nuevo": NEW_GROUP_AWARD,
             "porcentajes_individuales": PERCENTAGES,
             "nota": "Sólo configuración; el recálculo de cachés queda para la corrida conjunta."},
            ensure_ascii=False,
        )
        db.execute(
            """INSERT INTO lab_ajuste_umbral_auditoria(ejecucion,tipo,payload_json)
               VALUES(?,?,?)""",
            (execution, "refrigerados_armado_otras_15_antes", audit_payload),
        )
        changed = db.execute(
            """UPDATE lab_parametro_grupal SET uc_por_operario=?,premio_grupal=?,
                       updated_at=CURRENT_TIMESTAMP
               WHERE activo=1 AND sector=? AND funcion_legajero=?
                 AND UPPER(TRIM(operacion_medible))=? AND COALESCE(division_madre,'')=?""",
            (NEW_OBJECTIVE, NEW_GROUP_AWARD, sector, function, operation, division),
        )
        if changed.rowcount != 3:
            raise RuntimeError(f"Se actualizaron {changed.rowcount} parámetros; se esperaban 3.")

        for turn in ("1", "2", "3"):
            for level, lower, upper, pct in thresholds(NEW_OBJECTIVE):
                changed = db.execute(
                    """UPDATE lab_escala_individual_grupal
                       SET desde_uc=?,hasta_uc=?,pct_sobre_anterior=?,updated_at=CURRENT_TIMESTAMP
                       WHERE activo=1 AND sector=? AND funcion_legajero=? AND turno=?
                         AND UPPER(TRIM(operacion_medible))=?
                         AND COALESCE(division_madre,'')=? AND nivel=?""",
                    (lower, upper, pct, sector, function, turn, operation, division, level),
                )
                if changed.rowcount != 1:
                    raise RuntimeError(f"No se actualizó exactamente un tramo: turno={turn}, nivel={level}.")
        db.commit()
        print(json.dumps({
            "ok": True, "ejecucion": execution, "perfil": PROFILE,
            "turnos": 3, "objetivo": NEW_OBJECTIVE, "factor_ausentismo": 5,
            "premio_grupal": NEW_GROUP_AWARD,
            "escala_individual_uc": [
                {"nivel": level, "desde": lower, "hasta": upper,
                 "premio_conservado": next(float(row["premio"]) for row in scales
                                            if int(row["nivel"]) == level)}
                for level, lower, upper, _ in thresholds(NEW_OBJECTIVE)
            ], "caches_recalculados": False,
        }, ensure_ascii=False, indent=2))
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
