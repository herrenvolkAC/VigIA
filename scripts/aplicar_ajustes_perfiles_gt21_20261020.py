"""Apply proposed settings for active profiles with modeled increase >21%.

This updates parameter rows and regenerates individual UC thresholds from the
stored percentages. It deliberately does not recalculate any cache.
"""
from __future__ import annotations

from datetime import datetime
import json
import math
from pathlib import Path
import sqlite3


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "datos" / "laboratorio_premios.db"
ESTIMATE_PATH = ROOT / "outputs" / "estimacion_ajustes_perfiles_mayor_21_20261020.json"


def build_thresholds(objective: float, pcts: list[float]) -> list[tuple[int, int, int]]:
    value = float(objective)
    starts: list[int] = []
    for pct in pcts:
        value *= 1 + pct / 100
        starts.append(math.ceil(value - 1e-9))
    return [(level, starts[level - 1], starts[level] if level < 5 else 0)
            for level in range(1, 6)]


def main() -> None:
    estimate = json.loads(ESTIMATE_PATH.read_text(encoding="utf-8"))
    candidates = estimate["profiles_above_21_adjusted"]
    if not candidates or any("error" in item for item in candidates):
        raise RuntimeError("La estimación no contiene propuestas completas.")

    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    execution = datetime.now().astimezone().isoformat(timespec="seconds")
    changes = []
    try:
        db.execute("BEGIN IMMEDIATE")
        for item in candidates:
            sector, function, operation, division = item["profile"]
            objective = float(item["proposal"]["objective"])
            award = float(item["proposal"]["group_award"])
            params = [dict(r) for r in db.execute(
                """SELECT * FROM lab_parametro_grupal WHERE activo=1 AND sector=?
                   AND funcion_legajero=? AND UPPER(TRIM(operacion_medible))=?
                   AND COALESCE(division_madre,'')=? ORDER BY CAST(turno AS INTEGER),turno""",
                (sector, function, operation, division))]
            scales = [dict(r) for r in db.execute(
                """SELECT * FROM lab_escala_individual_grupal WHERE activo=1 AND sector=?
                   AND funcion_legajero=? AND UPPER(TRIM(operacion_medible))=?
                   AND COALESCE(division_madre,'')=? ORDER BY CAST(turno AS INTEGER),turno,nivel""",
                (sector, function, operation, division))]
            if len(params) != 3 or len(scales) != 15:
                raise RuntimeError(f"Perfil inesperado {item['profile']}: parámetros={len(params)}, escalas={len(scales)}")
            if {str(p["turno"]) for p in params} != {"1", "2", "3"}:
                raise RuntimeError(f"Turnos incompletos en {item['profile']}.")
            if len({(float(p["uc_por_operario"]), float(p["premio_grupal"])) for p in params}) != 1:
                raise RuntimeError(f"Parámetros actuales no son homogéneos entre turnos en {item['profile']}.")
            by_turn: dict[str, list[dict]] = {}
            for scale in scales:
                by_turn.setdefault(str(scale["turno"]), []).append(scale)
            if any(len(rows) != 5 or {int(r["nivel"]) for r in rows} != {1, 2, 3, 4, 5}
                   for rows in by_turn.values()):
                raise RuntimeError(f"Escala incompleta en {item['profile']}.")

            before = {"parametros": params, "escalas": scales}
            for param in params:
                db.execute(
                    """UPDATE lab_parametro_grupal SET uc_por_operario=?,premio_grupal=?,
                       updated_at=CURRENT_TIMESTAMP WHERE activo=1 AND sector=?
                       AND funcion_legajero=? AND turno=? AND UPPER(TRIM(operacion_medible))=?
                       AND COALESCE(division_madre,'')=?""",
                    (objective, award, sector, function, param["turno"], operation, division))
            for turn, rows in by_turn.items():
                rows.sort(key=lambda r: int(r["nivel"]))
                pcts = [float(r["pct_sobre_anterior"]) for r in rows]
                for level, low, high in build_thresholds(objective, pcts):
                    scale = rows[level - 1]
                    db.execute(
                        """UPDATE lab_escala_individual_grupal SET desde_uc=?,hasta_uc=?,
                           updated_at=CURRENT_TIMESTAMP WHERE activo=1 AND sector=?
                           AND funcion_legajero=? AND turno=? AND UPPER(TRIM(operacion_medible))=?
                           AND COALESCE(division_madre,'')=? AND nivel=?""",
                        (low, high, sector, function, turn, operation, division, level))

            params_after = [dict(r) for r in db.execute(
                "SELECT * FROM lab_parametro_grupal WHERE activo=1 AND sector=? AND funcion_legajero=? AND UPPER(TRIM(operacion_medible))=? AND COALESCE(division_madre,'')=? ORDER BY CAST(turno AS INTEGER),turno",
                (sector, function, operation, division))]
            scales_after = [dict(r) for r in db.execute(
                "SELECT * FROM lab_escala_individual_grupal WHERE activo=1 AND sector=? AND funcion_legajero=? AND UPPER(TRIM(operacion_medible))=? AND COALESCE(division_madre,'')=? ORDER BY CAST(turno AS INTEGER),turno,nivel",
                (sector, function, operation, division))]
            changes.append({
                "perfil": item["profile"], "antes": before,
                "despues": {"parametros": params_after, "escalas": scales_after},
                "estimacion": item["proposal"],
            })

        payload = json.dumps({
            "estimacion_archivo": str(ESTIMATE_PATH.relative_to(ROOT)),
            "cache_origen": estimate["cache_calculado_at"],
            "snapshot_pago_actual": estimate["snapshot"],
            "nota": "Parámetros y umbrales actualizados; caches sin recalcular, pendiente de confirmación del usuario.",
            "perfiles": changes,
        }, ensure_ascii=False)
        db.execute(
            "INSERT INTO lab_ajuste_umbral_auditoria(ejecucion,tipo,payload_json) VALUES(?,?,?)",
            (execution, "ajuste_perfiles_mayor_21_20261020_antes", payload))
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    print(json.dumps({"ok": True, "ejecucion": execution,
                      "perfiles_actualizados": len(changes),
                      "caches_recalculados": False,
                      "perfiles": [{"perfil": c["perfil"],
                                    "objetivo": c["estimacion"]["objective"],
                                    "premio_grupal": c["estimacion"]["group_award"],
                                    "umbrales": c["estimacion"]["thresholds"]}
                                   for c in changes]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
