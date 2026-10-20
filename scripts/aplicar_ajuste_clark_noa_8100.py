"""Actualiza solo el premio grupal de NOA · Clark y recalcula agosto-septiembre."""
from __future__ import annotations

import asyncio
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import routers.estudio_premios_productividad as estudio
from generar_informe_gerencial_umbrales import analyze

PERIOD = ("2026-08-01", "2026-09-30")
KEY = ("CD-NOA", "AUTOELEVADORISTA ARMADO Y GUARDADO NOA", "CLARK", "6")
OLD_AWARD = 6800.0
NEW_AWARD = 8100.0
OBJECTIVE = 155.0


async def admin_local(_request):
    return {"role": "admin", "device_status": "approved"}


def persist() -> str:
    db = sqlite3.connect(ROOT / "datos" / "laboratorio_premios.db", timeout=120)
    db.row_factory = sqlite3.Row
    execution = datetime.now().astimezone().isoformat(timespec="seconds")
    sector, function, operation, division = KEY
    try:
        db.execute("BEGIN IMMEDIATE")
        params = [dict(r) for r in db.execute("""SELECT * FROM lab_parametro_grupal
            WHERE activo=1 AND sector=? AND funcion_legajero=?
              AND UPPER(TRIM(operacion_medible))=? AND COALESCE(division_madre,'')=?
            ORDER BY turno""", (sector, function, operation, division))]
        scales = [dict(r) for r in db.execute("""SELECT * FROM lab_escala_individual_grupal
            WHERE activo=1 AND sector=? AND funcion_legajero=?
              AND UPPER(TRIM(operacion_medible))=? AND COALESCE(division_madre,'')=?
            ORDER BY turno,nivel""", (sector, function, operation, division))]
        if len(params) != 3 or {str(r["turno"]) for r in params} != {"1", "2", "3"}:
            raise RuntimeError(f"Parámetros activos inesperados: {len(params)} filas.")
        if any(float(r["premio_grupal"]) != OLD_AWARD or
               float(r["uc_por_operario"]) != OBJECTIVE for r in params):
            raise RuntimeError("NOA Clark ya no coincide con la base validada ($6.800 y 155 UC).")
        if len(scales) != 15 or {int(r["nivel"]) for r in scales} != {1, 2, 3, 4, 5}:
            raise RuntimeError(f"Escala individual inesperada: {len(scales)} filas activas.")

        db.execute("""CREATE TABLE IF NOT EXISTS lab_ajuste_umbral_auditoria(
            ejecucion TEXT NOT NULL, tipo TEXT NOT NULL, payload_json TEXT NOT NULL,
            creado TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(ejecucion,tipo))""")
        for kind, rows in (("parametros_antes_clark_noa", params),
                           ("escalas_sin_cambio_clark_noa", scales)):
            db.execute("INSERT INTO lab_ajuste_umbral_auditoria(ejecucion,tipo,payload_json) VALUES(?,?,?)",
                       (execution, kind, json.dumps(rows, ensure_ascii=False)))
        changed = db.execute("""UPDATE lab_parametro_grupal
            SET premio_grupal=?,updated_at=CURRENT_TIMESTAMP
            WHERE activo=1 AND sector=? AND funcion_legajero=?
              AND UPPER(TRIM(operacion_medible))=? AND COALESCE(division_madre,'')=?
              AND premio_grupal=? AND uc_por_operario=?""",
            (NEW_AWARD, sector, function, operation, division, OLD_AWARD, OBJECTIVE)).rowcount
        if changed != 3:
            raise RuntimeError(f"Se actualizaron {changed} filas; se esperaban 3.")
        db.execute("INSERT INTO lab_ajuste_umbral_auditoria(ejecucion,tipo,payload_json) VALUES(?,?,?)",
                   (execution, "escenario_clark_noa_aplicado", json.dumps({
                       "perfil": KEY, "premio_grupal_anterior": OLD_AWARD,
                       "premio_grupal_nuevo": NEW_AWARD, "umbral_uc_sin_cambio": OBJECTIVE,
                       "escala_individual_sin_cambio": True, "turnos": ["1", "2", "3"],
                       "periodo_recalculado": PERIOD,
                   }, ensure_ascii=False)))
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return execution


async def recalculate() -> dict:
    estudio._admin = admin_local
    group = await estudio.calculo_grupal(None, fecha_desde=PERIOD[0], fecha_hasta=PERIOD[1])
    individual = await estudio.recalcular_individual(None, fecha_desde=PERIOD[0], fecha_hasta=PERIOD[1])
    return {"grupos_diarios": len(group.get("nivel_2", [])),
            "legajo_dias": len(group.get("nivel_3", [])), "individual": individual}


async def main() -> None:
    execution = persist()
    counts = await recalculate()
    report = analyze(*PERIOD)
    matches = [p for p in report["perfiles"] if
               (p["sector"], p["funcion"], p["operacion"], str(p["division"])) == KEY]
    if len(matches) != 1:
        raise RuntimeError(f"El análisis final encontró {len(matches)} perfiles para {KEY}.")
    p = matches[0]
    more = less = equal = 0
    detail = []
    for person in p.get("piloto_legajos") or []:
        actual = sum(int(day.get("actual", 0)) for day in person["dias"])
        new = sum(int(day.get("grupal", 0)) + int(day.get("individual", 0)) +
                  int(day.get("polivalencia", 0)) for day in person["dias"])
        more += new > actual
        less += new < actual
        equal += new == actual
        detail.append({"legajo": str(person["legajo"]), "actual_centavos": actual,
                       "nuevo_centavos": new, "diferencia_centavos": new - actual})
    result = {
        "ejecucion": execution, "periodo": PERIOD, "recalculo": counts,
        "perfil": {"sector": p["sector"], "funcion": p["funcion"],
                   "operacion": p["operacion"], "division": p["division"],
                   "umbral_uc": p["objetivo"], "premio_grupal": p["premio_grupal"],
                   "dias_con_base": p["con_base"], "dias_que_cumple": p["cumple"],
                   "personas": p["personas"], "actual_centavos": p["actual_centavos"],
                   "nuevo_centavos": p["nuevo_centavos"], "mas": more, "menos": less,
                   "igual": equal, "detalle_legajos": detail},
    }
    output = ROOT / "outputs" / "ajuste_clark_noa_8100_20261020_resultado.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({**result, "resultado": str(output)}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
