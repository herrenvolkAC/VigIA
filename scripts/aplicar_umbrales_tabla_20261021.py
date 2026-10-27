"""Aplica la tabla de umbrales gerenciales y recalcula agosto-septiembre 2026.

Conserva los premios monetarios configurados. Guarda parámetros y escalas
anteriores en lab_ajuste_umbral_auditoria antes de modificar la base local.
"""
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

# (sector, función de legajero, operación medible, división madre): umbral
UMBRALES = {
    ("CD-SECOS - ZONA 1", "ARMADOR", "ARMADO", "1"): 1100,
    ("CD-SECOS - ZONA 2", "ARMADOR", "ARMADO", "1"): 1100,
    ("CD-ADMINISTRACION", "CONTROLADOR DE STOCK SECOS NOA", "CONTROL", "1,6"): 1300,
    ("CD-SECOS - ZONA 1", "AUTOELEVADORISTA", "CLARK", "1"): 118,
    ("CD-SECOS - ZONA 2", "AUTOELEVADORISTA", "CLARK", "1"): 118,
    ("CD-SECOS - ZONA 1", "RECEPCIONISTA", "RECEPCION", "1"): 81,
    ("CD-SECOS - ZONA 2", "RECEPCIONISTA DE SECO", "RECEPCION", "1"): 81,
    ("CD-SECOS - ZONA 1", "CARGADOR DE SECOS", "PALETS OPERADOS", "1,6"): 110,
    ("CD-NOA", "ARMADOR", "ARMADO", "6"): 850,
    ("CD-NOA", "AUTOELEVADORISTA ARMADO Y GUARDADO NOA", "CLARK", "6"): 118,
    ("CD-NOA", "RECEPCIONISTA", "RECEPCION", "6"): 70,
    ("CD-REFRIGERADOS", "ARMADOR", "ARMADO", "2,4"): 1000,
    ("CD-REFRIGERADOS", "ARMADOR T06", "ARMADO", "2,4"): 500,
    ("CD-REFRIGERADOS", "AUTOELEVADORISTA (REFRIG)", "CLARK", "2,4"): 118,
    ("CD-REFRIGERADOS", "CLARK CONGELADOS", "CLARK", "2,4"): 70,
    ("CD-REFRIGERADOS", "RECEPCIONISTA (REFRIG.)", "RECEPCION", "2,4"): 70,
    ("CD-REFRIGERADOS", "CARGADOR (REFRIG)", "PALETS OPERADOS", "2,4"): 120,
}


async def admin_local(_request):
    return {"role": "admin", "device_status": "approved"}


def save_audit_and_update() -> str:
    path = ROOT / "datos" / "laboratorio_premios.db"
    execution = datetime.now().astimezone().isoformat(timespec="seconds")
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    try:
        db.execute("BEGIN IMMEDIATE")
        params = [dict(r) for r in db.execute(
            "SELECT * FROM lab_parametro_grupal WHERE activo=1 ORDER BY sector,funcion_legajero,turno")]
        current = {}
        for row in params:
            key = (row["sector"], row["funcion_legajero"],
                   str(row["operacion_medible"] or "").strip().upper(),
                   str(row["division_madre"] or ""))
            current.setdefault(key, []).append(row)
        if set(current) != set(UMBRALES):
            missing = sorted(set(UMBRALES) - set(current))
            extra = sorted(set(current) - set(UMBRALES))
            raise RuntimeError(f"Perfiles activos distintos a lo esperado; faltantes={missing}; adicionales={extra}")
        for key, rows in current.items():
            if sorted(str(r["turno"]) for r in rows) != ["1", "2", "3"]:
                raise RuntimeError(f"Se esperaban turnos 1, 2 y 3 para {key}; encontrados={[r['turno'] for r in rows]}")

        scales = [dict(r) for r in db.execute(
            "SELECT * FROM lab_escala_individual_grupal WHERE activo=1 ORDER BY sector,funcion_legajero,turno,operacion_medible,division_madre,nivel")]
        db.execute("""INSERT INTO lab_ajuste_umbral_auditoria(ejecucion,tipo,payload_json)
            VALUES(?,?,?)""", (execution, "parametros_antes_tabla_20261021",
            json.dumps(params, ensure_ascii=False)))
        db.execute("""INSERT INTO lab_ajuste_umbral_auditoria(ejecucion,tipo,payload_json)
            VALUES(?,?,?)""", (execution, "escalas_antes_tabla_20261021",
            json.dumps(scales, ensure_ascii=False)))
        db.execute("""INSERT INTO lab_ajuste_umbral_auditoria(ejecucion,tipo,payload_json)
            VALUES(?,?,?)""", (execution, "umbrales_aplicados_tabla_20261021",
            json.dumps({"umbrales": [{"perfil": list(k), "umbral": v} for k, v in UMBRALES.items()],
                        "premios_grupales_y_montos_individuales": "conservados",
                        "periodo_recalculado": PERIOD}, ensure_ascii=False)))

        for (sector, function, operation, division), threshold in UMBRALES.items():
            cur = db.execute("""UPDATE lab_parametro_grupal SET uc_por_operario=?,updated_at=CURRENT_TIMESTAMP
                WHERE activo=1 AND sector=? AND funcion_legajero=?
                  AND UPPER(TRIM(operacion_medible))=? AND COALESCE(division_madre,'')=?""",
                (threshold, sector, function, operation, division))
            if cur.rowcount != 3:
                raise RuntimeError(f"Actualizadas {cur.rowcount} filas, se esperaban 3 para {(sector,function,operation,division)}")
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return execution


async def main() -> None:
    estudio._admin = admin_local
    execution = save_audit_and_update()
    scales_result = await estudio.generar_escalas_individuales_grupales(None)
    group = await estudio.calculo_grupal(None, *PERIOD)
    individual = await estudio.recalcular_individual(None, *PERIOD)
    report = analyze(*PERIOD)

    if len(report["perfiles"]) != len(UMBRALES):
        raise RuntimeError(f"Validación posterior: {len(report['perfiles'])} perfiles; se esperaban {len(UMBRALES)}")
    for profile in report["perfiles"]:
        key = (profile["sector"], profile["funcion"], profile["operacion"], profile["division"])
        expected = UMBRALES.get(key)
        if expected is None or float(profile["objetivo"]) != expected:
            raise RuntimeError(f"Umbral posterior incorrecto para {key}: {profile['objetivo']} != {expected}")

    zero_group_profiles = [
        (p["sector"], p["funcion_legajero"], p["operacion_medible"], float(p["premio_grupal"] or 0))
        for p in _read_active_params()
        if float(p["premio_grupal"] or 0) == 0
    ]
    print(json.dumps({
        "ok": True,
        "auditoria": execution,
        "periodo": PERIOD,
        "dias_laborables": report["dias"],
        "perfiles_actualizados": len(report["perfiles"]),
        "perfiles_por_turno": scales_result.get("perfiles"),
        "filas_escala_generadas": scales_result.get("filas"),
        "grupos_diarios_recalculados": len(group.get("nivel_2", [])),
        "legajo_dias_recalculados": len(group.get("nivel_3", [])),
        "resultado_individual": individual,
        "pago_actual_centavos": sum(p["actual_centavos"] for p in report["perfiles"]),
        "pago_nuevo_centavos": sum(p["nuevo_centavos"] for p in report["perfiles"]),
        "perfiles_sin_premio_grupal": zero_group_profiles,
        "perfiles": [{
            "sector": p["sector"], "funcion": p["funcion"], "operacion": p["operacion"],
            "division": p["division"], "umbral": p["objetivo"], "premio_grupal": p["premio_grupal"],
            "dias_cumple": p["cumple"], "dias_evaluados": p["dias"],
            "nuevo_centavos": p["nuevo_centavos"], "actual_centavos": p["actual_centavos"],
        } for p in report["perfiles"]],
    }, ensure_ascii=False, indent=2))


def _read_active_params() -> list[dict]:
    db = sqlite3.connect((ROOT / "datos" / "laboratorio_premios.db").as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in db.execute("SELECT * FROM lab_parametro_grupal WHERE activo=1")]
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
