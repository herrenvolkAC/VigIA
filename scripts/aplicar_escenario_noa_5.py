"""Ajusta los importes NOA para aproximar +5% por operación y recalcula agosto-septiembre.

El umbral/criterio de producción no se modifica. Se buscan importes de grupal e
individual redondeados a $100, procurando conservar la relación actual entre
ambos componentes (factor grupal/individual entre 0.85 y 1.15) y reducir la
cantidad y magnitud de legajos que quedan por debajo del pago vigente.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from generar_informe_gerencial_umbrales import analyze
import routers.estudio_premios_productividad as estudio

PERIOD = ("2026-08-01", "2026-09-30")
TARGET = 1.05
FACTOR_RATIO = (0.85, 1.15)
PROFILE_KEYS = {
    ("CD-NOA", "ARMADOR", "ARMADO", "6"),
    ("CD-NOA", "AUTOELEVADORISTA ARMADO Y GUARDADO NOA", "CLARK", "6"),
    ("CD-NOA", "RECEPCIONISTA", "RECEPCION", "6"),
}


def round100(value: float) -> int:
    return int(round(value / 100.0) * 100)


def profile_key(p: dict) -> tuple[str, str, str, str]:
    return (p["sector"], p["funcion"], p["operacion"], str(p["division"]))


def event_counts(person: dict) -> tuple[int, dict[int, int], int]:
    group_events = 0
    levels = {level: 0 for level in range(1, 6)}
    actual = 0
    for day in person["dias"]:
        actual += int(day["actual"])
        group_events += int(day["grupal"] > 0 or day["polivalencia"] > 0)
        level = int(day["nivel"])
        if day["individual"] > 0 and level in levels:
            levels[level] += 1
    return group_events, levels, actual


def choose_profile(p: dict) -> dict:
    people = p.get("piloto_legajos") or []
    if not people:
        raise RuntimeError(f"El perfil no tiene detalle por legajo: {profile_key(p)}")
    group_base = int(round(float(p["premio_grupal"])))
    individual_base = {int(row["nivel"]): int(round(float(row["premio"])))
                       for row in p["escala_individual"]}
    if set(individual_base) != {1, 2, 3, 4, 5}:
        raise RuntimeError(f"Escala individual incompleta en {profile_key(p)}")

    facts = []
    actual_total = 0
    individual_base_total = 0
    group_events_total = 0
    for person in people:
        groups, levels, actual = event_counts(person)
        facts.append((str(person["legajo"]), groups, levels, actual))
        actual_total += actual
        group_events_total += groups
        individual_base_total += sum(levels[level] * individual_base[level] * 100
                                     for level in range(1, 6))

    target_total = round(actual_total * TARGET)
    candidates = []
    if individual_base_total <= 0:
        raise RuntimeError(f"Sin jornadas individuales para ajustar {profile_key(p)}")
    for step in range(50, 201):
        group_factor = step / 100
        group_award = round100(group_base * group_factor)
        group_total = group_events_total * group_award * 100
        individual_factor = (target_total - group_total) / individual_base_total
        if individual_factor <= 0:
            continue
        ratio = group_factor / individual_factor
        if not FACTOR_RATIO[0] <= ratio <= FACTOR_RATIO[1]:
            continue
        individual_awards = {
            level: round100(individual_base[level] * individual_factor)
            for level in range(1, 6)
        }

        rows = []
        for legajo, group_events, levels, actual in facts:
            group_poly = group_events * group_award * 100
            individual = sum(levels[level] * individual_awards[level] * 100
                             for level in range(1, 6))
            rows.append({"legajo": legajo, "actual_centavos": actual,
                         "grupal_centavos": group_poly,
                         "individual_centavos": individual,
                         "nuevo_centavos": group_poly + individual})
        new_total = sum(row["nuevo_centavos"] for row in rows)
        deltas = [row["nuevo_centavos"] - row["actual_centavos"] for row in rows]
        less = [delta for delta in deltas if delta < 0]
        score = (
            len(less),
            sum(-delta for delta in less),
            max((-delta for delta in less), default=0),
            abs(new_total - target_total),
            abs(group_factor - individual_factor),
            abs(group_factor - 1) + abs(individual_factor - 1),
        )
        candidates.append((score, group_award, individual_awards, rows,
                           group_factor, individual_factor, new_total))

    if not candidates:
        raise RuntimeError(f"No se encontró un escenario válido para {profile_key(p)}")
    score, group_award, individual_awards, rows, group_factor, individual_factor, new_total = min(
        candidates, key=lambda candidate: candidate[0])
    return {
        "key": profile_key(p),
        "grupo": group_award,
        "individual": individual_awards,
        "actual_centavos": actual_total,
        "nuevo_centavos": new_total,
        "target_centavos": target_total,
        "group_factor": group_factor,
        "individual_factor": individual_factor,
        "rows": rows,
        "more": sum(row["nuevo_centavos"] > row["actual_centavos"] for row in rows),
        "less": sum(row["nuevo_centavos"] < row["actual_centavos"] for row in rows),
        "equal": sum(row["nuevo_centavos"] == row["actual_centavos"] for row in rows),
    }


def prepare(report: dict) -> dict[str, dict]:
    profiles = [p for p in report["perfiles"] if p.get("sector") == "CD-NOA"]
    found = {profile_key(p) for p in profiles}
    if found != PROFILE_KEYS:
        raise RuntimeError(f"Los perfiles NOA no coinciden con los esperados: {found}")
    return {p["id"]: {**choose_profile(p), "sector": p["sector"],
                       "funcion": p["funcion"], "operacion": p["operacion"],
                       "division": str(p["division"])} for p in profiles}


def persist(settings: dict[str, dict], execution: str) -> None:
    db = sqlite3.connect(ROOT / "datos/laboratorio_premios.db")
    db.row_factory = sqlite3.Row
    try:
        db.execute("BEGIN IMMEDIATE")
        before_params, before_scales = [], []
        for value in settings.values():
            sector, function, operation, division = value["key"]
            before_params.extend(dict(r) for r in db.execute("""SELECT * FROM lab_parametro_grupal
                WHERE activo=1 AND sector=? AND funcion_legajero=?
                  AND UPPER(TRIM(operacion_medible))=? AND COALESCE(division_madre,'')=?
                ORDER BY turno""", (sector, function, operation, division)))
            before_scales.extend(dict(r) for r in db.execute("""SELECT * FROM lab_escala_individual_grupal
                WHERE activo=1 AND sector=? AND funcion_legajero=?
                  AND UPPER(TRIM(operacion_medible))=? AND COALESCE(division_madre,'')=?
                ORDER BY turno,nivel""", (sector, function, operation, division)))
        if len(before_params) != 9 or len(before_scales) != 45:
            raise RuntimeError(f"Filas activas NOA inesperadas: parámetros={len(before_params)}, escalas={len(before_scales)}")
        db.execute("""CREATE TABLE IF NOT EXISTS lab_ajuste_umbral_auditoria(
            ejecucion TEXT NOT NULL, tipo TEXT NOT NULL, payload_json TEXT NOT NULL,
            creado TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(ejecucion,tipo))""")
        for kind, payload in (("parametros_antes_noa5", before_params),
                              ("escalas_antes_noa5", before_scales)):
            db.execute("INSERT INTO lab_ajuste_umbral_auditoria(ejecucion,tipo,payload_json) VALUES(?,?,?)",
                       (execution, kind, json.dumps(payload, ensure_ascii=False)))
        for value in settings.values():
            sector, function, operation, division = value["key"]
            cur = db.execute("""UPDATE lab_parametro_grupal SET premio_grupal=?,updated_at=CURRENT_TIMESTAMP
                WHERE activo=1 AND sector=? AND funcion_legajero=?
                  AND UPPER(TRIM(operacion_medible))=? AND COALESCE(division_madre,'')=?""",
                             (value["grupo"], sector, function, operation, division))
            if cur.rowcount != 3:
                raise RuntimeError(f"Parámetros inesperados para {value['key']}: {cur.rowcount}")
            for level, award in value["individual"].items():
                cur = db.execute("""UPDATE lab_escala_individual_grupal SET premio=?,updated_at=CURRENT_TIMESTAMP
                    WHERE activo=1 AND sector=? AND funcion_legajero=?
                      AND UPPER(TRIM(operacion_medible))=? AND COALESCE(division_madre,'')=? AND nivel=?""",
                                 (award, sector, function, operation, division, level))
                if cur.rowcount != 3:
                    raise RuntimeError(f"Escalas inesperadas para {value['key']}/N{level}: {cur.rowcount}")
        audit = {key: {k: v for k, v in value.items() if k != "rows"}
                 for key, value in settings.items()}
        db.execute("INSERT INTO lab_ajuste_umbral_auditoria(ejecucion,tipo,payload_json) VALUES(?,?,?)",
                   (execution, "escenario_noa5", json.dumps(audit, ensure_ascii=False)))
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


async def admin_local(_request):
    return {"role": "admin", "device_status": "approved"}


async def recalculate() -> dict:
    estudio._admin = admin_local
    group = await estudio.calculo_grupal(None, fecha_desde=PERIOD[0], fecha_hasta=PERIOD[1])
    individual = await estudio.recalcular_individual(None, fecha_desde=PERIOD[0], fecha_hasta=PERIOD[1])
    return {"grupos_diarios": len(group.get("nivel_2", [])),
            "legajo_dias": len(group.get("nivel_3", [])), "individual": individual}


def verified_summary(settings: dict[str, dict], report: dict) -> dict:
    by_key = {profile_key(p): p for p in report["perfiles"] if p.get("sector") == "CD-NOA"}
    result = {}
    for value in settings.values():
        key = value["key"]
        p = by_key[key]
        people = p["piloto_legajos"]
        expected = {row["legajo"]: row for row in value["rows"]}
        if len(people) != len(expected):
            raise RuntimeError(f"Población distinta al verificar {key}")
        for person in people:
            rows = person["dias"]
            actual = sum(int(day["actual"]) for day in rows)
            new = sum(int(day["grupal"]) + int(day["individual"]) + int(day["polivalencia"])
                      for day in rows)
            if actual != expected[person["legajo"]]["actual_centavos"]:
                raise RuntimeError(f"Pago actual varió inesperadamente para {person['legajo']}")
            expected_new = expected[person["legajo"]]["nuevo_centavos"]
            if new != expected_new:
                raise RuntimeError(f"Pago nuevo difiere en {person['legajo']}: {new} vs {expected_new}")
        result["/".join(key)] = {
            "actual_centavos": int(p["actual_centavos"]),
            "nuevo_centavos": int(p["nuevo_centavos"]),
            "variacion_pct": (p["nuevo_centavos"] / p["actual_centavos"] - 1) * 100,
            "mas": int(p["mas"]), "menos": int(p["menos"]), "igual": int(p["igual"]),
            "personas": int(p["personas"]),
            "grupo": value["grupo"], "individual": value["individual"],
            "group_factor": value["group_factor"],
            "individual_factor": value["individual_factor"],
            "per_legajo": value["rows"],
        }
    actual = sum(item["actual_centavos"] for item in result.values())
    new = sum(item["nuevo_centavos"] for item in result.values())
    result["TOTAL NOA"] = {
        "actual_centavos": actual, "nuevo_centavos": new,
        "variacion_pct": (new / actual - 1) * 100,
        "mas": sum(item["mas"] for key, item in result.items() if key != "TOTAL NOA"),
        "menos": sum(item["menos"] for key, item in result.items() if key != "TOTAL NOA"),
        "igual": sum(item["igual"] for key, item in result.items() if key != "TOTAL NOA"),
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Simula sin guardar ni recalcular.")
    args = parser.parse_args()
    original = analyze(*PERIOD)
    settings = prepare(original)
    if args.dry_run:
        print(json.dumps({k: {x: y for x, y in v.items() if x != "rows"}
                          for k, v in settings.items()}, ensure_ascii=False, indent=2))
        return
    execution = datetime.now().strftime("noa5_%Y%m%d_%H%M%S")
    persist(settings, execution)
    recalculated = asyncio.run(recalculate())
    fresh = analyze(*PERIOD)
    summary = verified_summary(settings, fresh)
    print(json.dumps({"ejecucion": execution, "periodo": PERIOD,
                      "fuente_cache": fresh["cache_grupal"],
                      "snapshot_pagos": fresh["snapshot_pagos"],
                      "recalculo": recalculated, "resultado": summary},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
