"""Ajusta pagos de Secos para acercar cada zona a +15% frente al actual.

El umbral de productividad no cambia. Armado conserva premio y escala comunes
en Zona 1 y Zona 2. El script registra la configuración previa en la auditoría,
recalcula las cachés de agosto-septiembre y genera un HTML nuevo para revisión.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import defaultdict
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from generar_informe_gerencial_umbrales import analyze, render
import routers.estudio_premios_productividad as estudio

SOURCE_REPORT = ROOT / "outputs/informe_gerencial_umbrales_75_balanceado_20261019.json"
FAMILY_SCENARIO = ROOT / "outputs/simulacion_secos_15_sin_cambios.json"
OUTPUT_BASE = ROOT / "outputs/informe_gerencial_secos_zonas15_20261019.html"
PERIOD = ("2026-08-01", "2026-09-30")
ZONES = ("CD-SECOS - ZONA 1", "CD-SECOS - ZONA 2")
FAMILY_BY_PROFILE = {
    "perfil-1": "ARMADO SECOS",
    "perfil-2": "CLARK SECOS",
    "perfil-3": "CARGA SECOS",
    "perfil-5": "ARMADO SECOS",
    "perfil-6": "CLARK SECOS",
    "perfil-7": "RECEPCION SECOS",
}


def round100(value: float) -> int:
    return int(round(value / 100.0) * 100)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def event_counts(person: dict) -> tuple[int, dict[int, int]]:
    group_events = 0
    levels = {level: 0 for level in range(1, 6)}
    for day in person["dias"]:
        has_group = day["grupal"] > 0
        has_poly = day["polivalencia"] > 0
        if has_group and has_poly:
            raise ValueError(f"Doble pago grupal/polivalencia: {person['legajo']} {day['fecha']}")
        group_events += int(has_group or has_poly)
        if day["individual"] > 0 and 1 <= int(day["nivel"]) <= 5:
            levels[int(day["nivel"])] += 1
    return group_events, levels


def prepare(report: dict, family_scenario: dict) -> tuple[dict, dict]:
    profiles = {p["id"]: p for p in report["perfiles"]}
    for pid in FAMILY_BY_PROFILE:
        if pid not in profiles:
            raise ValueError(f"Falta perfil en informe: {pid}")
        p = profiles[pid]
        if p["sector"] not in ZONES or not p.get("piloto_legajos"):
            raise ValueError(f"Perfil sin base Secos válida: {pid} / {p['sector']}")

    # La simulación familiar eleva cada operación de Secos a +15% y elige
    # importes redondos reduciendo los legajos perjudicados.
    family_amounts: dict[str, dict] = {}
    family_totals: dict[str, float] = {}
    family_actuals = defaultdict(int)
    actual_by_zone = defaultdict(int)
    family_new_by_zone = defaultdict(int)
    family_arm_by_zone = defaultdict(int)
    for pid, family in FAMILY_BY_PROFILE.items():
        p = profiles[pid]
        amounts = family_scenario[family]["montos"][pid]
        group_award = int(amounts["grupal"])
        individual_awards = [int(x) for x in amounts["individual"]]
        if len(individual_awards) != 5:
            raise ValueError(f"Escala incompleta para {pid}")
        new_cents = 0
        for person in p["piloto_legajos"]:
            group_events, levels = event_counts(person)
            new_cents += group_events * group_award * 100
            new_cents += sum(levels[level] * individual_awards[level - 1] * 100
                             for level in range(1, 6))
        family_amounts[pid] = {"grupal": group_award, "individual": individual_awards}
        family_totals[pid] = new_cents
        family_actuals[family] += int(p["actual_centavos"])
        if abs(sum(int(d["actual"]) for person in p["piloto_legajos"] for d in person["dias"])
               - int(p["actual_centavos"])) > 1:
            raise ValueError(f"Los importes históricos del detalle no coinciden para {pid}")
        actual_by_zone[p["sector"]] += int(p["actual_centavos"])
        family_new_by_zone[p["sector"]] += new_cents
        if p["operacion"] == "ARMADO":
            family_arm_by_zone[p["sector"]] += new_cents

    for family in set(FAMILY_BY_PROFILE.values()):
        expected_actual = round(float(family_scenario[family]["actual"]) * 100)
        expected_new = round(float(family_scenario[family]["nuevo"]) * 100)
        actual = family_actuals[family]
        new = sum(family_totals[pid] for pid, f in FAMILY_BY_PROFILE.items() if f == family)
        if abs(actual - expected_actual) > 1:
            raise ValueError(f"Base histórica inesperada para {family}: {actual} vs {expected_actual}")
        if abs(new - expected_new) > max(10000, expected_new * 0.01):
            raise ValueError(f"Importes redondeados inesperados para {family}: {new} vs {expected_new}")

    # Con Armado compartido, cada zona recibe un factor para sus otros perfiles
    # que deja su bolsa total alrededor de +15% del pago actual.
    zone_factors = {}
    for zone in ZONES:
        non_arm = family_new_by_zone[zone] - family_arm_by_zone[zone]
        target = actual_by_zone[zone] * 1.15
        if non_arm <= 0:
            raise ValueError(f"No hay base no-Armado para ajustar {zone}")
        zone_factors[zone] = (target - family_arm_by_zone[zone]) / non_arm

    settings = {}
    summary_by_zone = defaultdict(lambda: {"actual": 0, "new": 0, "group_poly": 0,
                                           "individual": 0, "people": defaultdict(lambda: [0, 0])})
    profile_summary = {}
    for pid, family in FAMILY_BY_PROFILE.items():
        p = profiles[pid]
        base = family_amounts[pid]
        factor = 1.0 if p["operacion"] == "ARMADO" else zone_factors[p["sector"]]
        group_award = base["grupal"] if p["operacion"] == "ARMADO" else round100(base["grupal"] * factor)
        individual_awards = (base["individual"] if p["operacion"] == "ARMADO"
                             else [round100(x * factor) for x in base["individual"]])
        settings[pid] = {"sector": p["sector"], "funcion": p["funcion"],
                         "operacion": p["operacion"], "division": p["division"],
                         "grupal": group_award,
                         "individual": {str(level): individual_awards[level - 1]
                                        for level in range(1, 6)},
                         "factor_sobre_escenario_familiar": factor}
        zone = summary_by_zone[p["sector"]]
        zone["actual"] += int(p["actual_centavos"])
        profile_new = 0
        profile_group_poly = 0
        profile_individual = 0
        for person in p["piloto_legajos"]:
            legajo = str(person["legajo"])
            actual = sum(int(d["actual"]) for d in person["dias"])
            group_events, levels = event_counts(person)
            group_poly = group_events * group_award * 100
            individual = sum(levels[level] * individual_awards[level - 1] * 100
                             for level in range(1, 6))
            new = group_poly + individual
            profile_new += new
            profile_group_poly += group_poly
            profile_individual += individual
            person_summary = zone["people"][legajo]
            person_summary[0] += actual
            person_summary[1] += new
        zone["new"] += profile_new
        zone["group_poly"] += profile_group_poly
        zone["individual"] += profile_individual
        profile_summary[pid] = {"actual": int(p["actual_centavos"]), "new": profile_new,
                                "more": 0, "less": 0, "equal": 0}

    for zone in ZONES:
        z = summary_by_zone[zone]
        z["more"] = sum(n > a for a, n in z["people"].values())
        z["less"] = sum(n < a for a, n in z["people"].values())
        z["equal"] = sum(n == a for a, n in z["people"].values())
        z["variation_pct"] = (z["new"] / z["actual"] - 1) * 100 if z["actual"] else 0
        z["target"] = z["actual"] * 1.15
        z["gap_to_target"] = z["new"] - z["target"]
        z["group_poly_pct"] = z["group_poly"] / z["new"] * 100 if z["new"] else 0
        z["individual_pct"] = z["individual"] / z["new"] * 100 if z["new"] else 0
        z["people"] = len(z["people"])
        z["actual"] /= 100
        z["new"] /= 100
        z["target"] /= 100
        z["gap_to_target"] /= 100
        z["group_poly"] /= 100
        z["individual"] /= 100
        for key in ("variation_pct", "group_poly_pct", "individual_pct"):
            z[key] = round(z[key], 2)
    return settings, {"zones": summary_by_zone, "profiles": profile_summary,
                      "zone_factors": zone_factors}


async def admin_local(_request):
    return {"role": "admin", "device_status": "approved"}


def persist(settings: dict, execution: str) -> None:
    db_path = ROOT / "datos/laboratorio_premios.db"
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    try:
        db.execute("BEGIN IMMEDIATE")
        db.execute("""CREATE TABLE IF NOT EXISTS lab_ajuste_umbral_auditoria(
            ejecucion TEXT NOT NULL, tipo TEXT NOT NULL, payload_json TEXT NOT NULL,
            creado TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(ejecucion,tipo))""")
        target_keys = set()
        for values in settings.values():
            target_keys.add((values["sector"], values["funcion"], values["operacion"], values["division"]))
        params_before = []
        scales_before = []
        for sector, function, operation, division in target_keys:
            params_before.extend(dict(r) for r in db.execute("""SELECT * FROM lab_parametro_grupal
                WHERE activo=1 AND sector=? AND funcion_legajero=? AND UPPER(TRIM(operacion_medible))=?
                  AND COALESCE(division_madre,'')=? ORDER BY turno""",
                                      (sector, function, operation, division)))
            scales_before.extend(dict(r) for r in db.execute("""SELECT * FROM lab_escala_individual_grupal
                WHERE activo=1 AND sector=? AND funcion_legajero=? AND UPPER(TRIM(operacion_medible))=?
                  AND COALESCE(division_madre,'')=? ORDER BY turno,nivel""",
                                      (sector, function, operation, division)))
        if len(params_before) != 18 or len(scales_before) != 90:
            raise RuntimeError(f"Filas activas inesperadas: parámetros={len(params_before)}, escalas={len(scales_before)}")
        db.execute("INSERT INTO lab_ajuste_umbral_auditoria(ejecucion,tipo,payload_json) VALUES(?,?,?)",
                   (execution, "parametros_antes_secos15",
                    json.dumps(params_before, ensure_ascii=False)))
        db.execute("INSERT INTO lab_ajuste_umbral_auditoria(ejecucion,tipo,payload_json) VALUES(?,?,?)",
                   (execution, "escalas_antes_secos15",
                    json.dumps(scales_before, ensure_ascii=False)))
        for values in settings.values():
            where = (values["sector"], values["funcion"], values["operacion"], values["division"])
            cur = db.execute("""UPDATE lab_parametro_grupal SET premio_grupal=?,updated_at=CURRENT_TIMESTAMP
                WHERE activo=1 AND sector=? AND funcion_legajero=?
                  AND UPPER(TRIM(operacion_medible))=? AND COALESCE(division_madre,'')=?""",
                             (values["grupal"], *where))
            if cur.rowcount != 3:
                raise RuntimeError(f"Parámetros inesperados para {where}: {cur.rowcount}")
            for level, award in values["individual"].items():
                cur = db.execute("""UPDATE lab_escala_individual_grupal SET premio=?,updated_at=CURRENT_TIMESTAMP
                    WHERE activo=1 AND sector=? AND funcion_legajero=?
                      AND UPPER(TRIM(operacion_medible))=? AND COALESCE(division_madre,'')=? AND nivel=?""",
                                 (award, *where, int(level)))
                if cur.rowcount != 3:
                    raise RuntimeError(f"Escalas inesperadas para {where}/N{level}: {cur.rowcount}")
        db.execute("INSERT INTO lab_ajuste_umbral_auditoria(ejecucion,tipo,payload_json) VALUES(?,?,?)",
                   (execution, "escenario_secos_zonas15",
                    json.dumps(settings, ensure_ascii=False)))
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


async def recalculate() -> dict:
    estudio._admin = admin_local
    group = await estudio.calculo_grupal(None, fecha_desde=PERIOD[0], fecha_hasta=PERIOD[1])
    individual = await estudio.recalcular_individual(None, fecha_desde=PERIOD[0], fecha_hasta=PERIOD[1])
    return {"grupos_diarios": len(group.get("nivel_2", [])),
            "legajo_dias": len(group.get("nivel_3", [])), "individual": individual}


def validate_final(report: dict) -> dict:
    zone_values = {}
    for zone in ZONES:
        rows = [p for p in report["perfiles"] if p["sector"] == zone]
        actual = sum(int(p["actual_centavos"]) for p in rows)
        new = sum(int(p["nuevo_centavos"]) for p in rows)
        people = defaultdict(lambda: [0, 0])
        for p in rows:
            for person in p.get("piloto_legajos", []):
                legajo = str(person["legajo"])
                people[legajo][0] += sum(int(d["actual"]) for d in person["dias"])
                people[legajo][1] += sum(int(d["grupal"]) + int(d["individual"]) + int(d["polivalencia"])
                                         for d in person["dias"])
        zone_values[zone] = {"actual": actual / 100, "nuevo": new / 100,
                             "variation_pct": (new / actual - 1) * 100 if actual else 0,
                             "more": sum(n > a for a, n in people.values()),
                             "less": sum(n < a for a, n in people.values()),
                             "equal": sum(n == a for a, n in people.values()),
                             "people": len(people)}
    return zone_values


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Valida y presenta el escenario sin guardar cambios.")
    args = parser.parse_args()
    original = read_json(SOURCE_REPORT)
    family = read_json(FAMILY_SCENARIO)
    fresh = analyze(*PERIOD)
    if fresh["cache_grupal"] != original["cache_grupal"] or fresh["snapshot_pagos"] != original["snapshot_pagos"]:
        raise RuntimeError("El reporte de partida quedó desactualizado; regenerarlo antes de aplicar.")
    settings, modeled = prepare(fresh, family)
    preview = {"periodo": PERIOD, "fuente_cache": fresh["cache_grupal"],
               "objetivo_por_zona_pct": 15, "premios": settings,
               "resultado_estimado": {z: {k: v for k, v in values.items() if k != "people"}
                                      for z, values in modeled["zones"].items()},
               "legajos_estimados_por_zona": {z: {k: modeled["zones"][z][k]
                                                   for k in ("people", "more", "less", "equal")}
                                               for z in ZONES}}
    (ROOT / "outputs/escenario_secos_zonas15_propuesto.json").write_text(
        json.dumps(preview, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.dry_run:
        print(json.dumps(preview, ensure_ascii=False, indent=2))
        return

    execution = datetime.now().astimezone().isoformat(timespec="seconds")
    persist(settings, execution)
    try:
        recalc = await recalculate()
        final = analyze(*PERIOD)
        validated = validate_final(final)
        if any(abs(values["variation_pct"] - 15) > 0.7 for values in validated.values()):
            raise RuntimeError(f"La recalculación se alejó del objetivo por zona: {validated}")
        final["escenario_aplicado"] = {"ejecucion": execution,
                                       "criterio": "bolsa aproximada +15% en cada zona; Armado común",
                                       "estimacion_previa": preview["resultado_estimado"],
                                       "recalculado": recalc,
                                       "validacion_final": validated}
        OUTPUT_BASE.write_text(render(final, compact=True), encoding="utf-8")
        OUTPUT_BASE.with_suffix(".json").write_text(
            json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8")
        db = sqlite3.connect(ROOT / "datos/laboratorio_premios.db")
        try:
            db.execute("INSERT INTO lab_ajuste_umbral_auditoria(ejecucion,tipo,payload_json) VALUES(?,?,?)",
                       (execution, "resultado_secos_zonas15",
                        json.dumps({"validacion_final": validated, "recalculado": recalc,
                                    "reporte_html": str(OUTPUT_BASE)}, ensure_ascii=False)))
            db.commit()
        finally:
            db.close()
        print(json.dumps({"ejecucion": execution, "recalculado": recalc,
                          "resultado_final": validated, "html": str(OUTPUT_BASE)}, ensure_ascii=False))
    except Exception:
        # If cache refresh or validation fails, restore the audited previous
        # amounts and regenerate the cache to avoid leaving mismatched inputs.
        db = sqlite3.connect(ROOT / "datos/laboratorio_premios.db")
        db.row_factory = sqlite3.Row
        try:
            before_params = json.loads(db.execute("SELECT payload_json FROM lab_ajuste_umbral_auditoria WHERE ejecucion=? AND tipo=?",
                                                  (execution, "parametros_antes_secos15")).fetchone()[0])
            before_scales = json.loads(db.execute("SELECT payload_json FROM lab_ajuste_umbral_auditoria WHERE ejecucion=? AND tipo=?",
                                                  (execution, "escalas_antes_secos15")).fetchone()[0])
            db.execute("BEGIN IMMEDIATE")
            for row in before_params:
                db.execute("""UPDATE lab_parametro_grupal SET premio_grupal=?,updated_at=CURRENT_TIMESTAMP
                    WHERE sector=? AND funcion_legajero=? AND turno=? AND UPPER(TRIM(operacion_medible))=?
                      AND COALESCE(division_madre,'')=?""",
                           (row["premio_grupal"], row["sector"], row["funcion_legajero"], row["turno"],
                            row["operacion_medible"], row["division_madre"]))
            for row in before_scales:
                db.execute("""UPDATE lab_escala_individual_grupal SET premio=?,updated_at=CURRENT_TIMESTAMP
                    WHERE sector=? AND funcion_legajero=? AND turno=? AND UPPER(TRIM(operacion_medible))=?
                      AND COALESCE(division_madre,'')=? AND nivel=?""",
                           (row["premio"], row["sector"], row["funcion_legajero"], row["turno"],
                            row["operacion_medible"], row["division_madre"], row["nivel"]))
            db.execute("INSERT INTO lab_ajuste_umbral_auditoria(ejecucion,tipo,payload_json) VALUES(?,?,?)",
                       (execution, "ajuste_secos_zonas15_revertido",
                        json.dumps({"motivo": "falló recalculo o validación; se restauraron premios previos"})))
            db.commit()
        finally:
            db.close()
        try:
            await recalculate()
        finally:
            raise


if __name__ == "__main__":
    asyncio.run(main())
