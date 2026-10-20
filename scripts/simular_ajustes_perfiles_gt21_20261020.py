"""Estimate August-September adjustments for profiles above +21%.

Read-only: recomputes group and individual awards from the latest cached
production/roster facts and active parameters. It does not update settings or
recalculate the application caches.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import json
import math
from pathlib import Path
import sqlite3


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "datos" / "laboratorio_premios.db"
FROM, TO = "20260801", "20260930"
TARGET_BAG = 1.205
TARGET_RANGE = (20.0, 21.0)
KNOWN_INVALID = ()
EQUIVALENTS = {
    "ARMADO": {"PICKING"},
    "CLARK": {"CLARK"},
    "CONTROL": {"CONTROL", "CONTROL PROCESOS MANUAL", "CONTROL DE PROCESOS CHP + CBF"},
    "RECEPCION": {"RECEPCION", "RECEPCION NOA", "RECEPCION SECOS",
                  "RECEPCION IMPORTADO DE NOA", "REFRIGERADOS | RECEPCION"},
    "PALETS OPERADOS": {"CARGA", "CARRETEO", "REFRIGERADOS | CARGA"},
}


def key(row: dict, operation_field: str = "operacion") -> tuple[str, str, str, str]:
    return (str(row.get("sector") or "").strip(),
            str(row.get("funcion_legajero") or row.get("funcion") or "").strip(),
            str(row.get(operation_field) or row.get("operacion_medible") or "").strip().upper(),
            str(row.get("division_madre") or "").strip())


def weekday(date: str) -> bool:
    return datetime.strptime(date, "%Y%m%d").weekday() < 5


def thresholds(objective: float, percentages: list[float]) -> list[int]:
    value = float(objective)
    result = []
    for percentage in percentages:
        value *= 1 + percentage / 100
        result.append(math.ceil(value - 1e-9))
    return result


def load_data():
    db = sqlite3.connect(DB_PATH.as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    cache = db.execute(
        """SELECT nivel_2_json,nivel_3_json,calculado_at FROM lab_calculo_grupal_cache
           WHERE fecha_desde=? AND fecha_hasta=? ORDER BY calculado_at DESC LIMIT 1""",
        (FROM, TO),
    ).fetchone()
    if not cache:
        raise RuntimeError("No existe cache grupal del período agosto-septiembre.")
    meta = db.execute("SELECT snapshot FROM lab_pago_actual_meta ORDER BY capturado DESC LIMIT 1").fetchone()
    if not meta:
        raise RuntimeError("No existe snapshot de pagos actuales.")
    params = [dict(r) for r in db.execute("SELECT * FROM lab_parametro_grupal WHERE activo=1")]
    scales = [dict(r) for r in db.execute("SELECT * FROM lab_escala_individual_grupal WHERE activo=1")]
    payroll = [dict(r) for r in db.execute(
        """SELECT CAST(legajo AS TEXT) legajo,fecha,UPPER(TRIM(operacion)) operacion,
                  SUM(pago_centavos) pago
           FROM lab_pago_actual_operacion WHERE snapshot=? AND fecha BETWEEN ? AND ?
           GROUP BY CAST(legajo AS TEXT),fecha,UPPER(TRIM(operacion))""",
        (meta["snapshot"], FROM, TO),
    )]
    db.close()
    return cache, params, scales, payroll, meta["snapshot"]


def main() -> None:
    cache, params, scales, payroll, snapshot = load_data()
    params_by_key: dict[tuple, list[dict]] = defaultdict(list)
    scales_by_key_turn: dict[tuple, list[dict]] = defaultdict(list)
    daily_map = {}
    roster_by_key: dict[tuple, list[dict]] = defaultdict(list)
    for row in params:
        params_by_key[key(row, "operacion_medible")].append(row)
    for row in scales:
        scales_by_key_turn[(key(row, "operacion_medible"), str(row["turno"]))].append(row)
    for row in json.loads(cache["nivel_2_json"]):
        if weekday(row["fecha"]):
            daily_map[(key(row), str(row["turno"]), row["fecha"])] = row
    for row in json.loads(cache["nivel_3_json"]):
        if weekday(row["fecha"]):
            roster_by_key[key(row)].append(row)
    actual_raw: dict[tuple[str, str, str], int] = defaultdict(int)
    for row in payroll:
        actual_raw[(str(row["legajo"]), row["fecha"], row["operacion"])] += int(row["pago"] or 0)

    def current_actual(profile_key: tuple, legajo: str, date: str) -> int:
        operations = EQUIVALENTS.get(profile_key[2], {profile_key[2]})
        return sum(actual_raw[(legajo, date, op)] for op in operations)

    def compute(profile_key: tuple, objective: float, group_award: float, regenerate: bool):
        turns = params_by_key[profile_key]
        factor = float(turns[0]["factor_ausentismo"])
        person_totals: dict[str, dict] = defaultdict(lambda: {
            "actual": 0, "group": 0, "poly": 0, "individual": 0,
            "group_days": 0, "poly_days": 0,
        })
        per_turn_scales = {}
        for parameter in turns:
            turn = str(parameter["turno"])
            rows = scales_by_key_turn[(profile_key, turn)]
            if regenerate:
                pcts = [float(next(s["pct_sobre_anterior"] for s in rows
                                   if int(s["nivel"]) == level))
                        for level in range(1, 6)]
                starts = thresholds(objective, pcts)
                per_turn_scales[turn] = [
                    {"nivel": level, "desde_uc": starts[level - 1],
                     "hasta_uc": starts[level] if level < 5 else 0,
                     "premio": float(next(s["premio"] for s in rows
                                          if int(s["nivel"]) == level))}
                    for level in range(1, 6)
                ]
            else:
                per_turn_scales[turn] = rows

        for row in roster_by_key[profile_key]:
            legajo = str(row["legajo"])
            person = person_totals[legajo]
            person["actual"] += current_actual(profile_key, legajo, row["fecha"])
            daily = daily_map.get((profile_key, str(row["turno"]), row["fecha"]), {})
            target = (float(daily.get("nomina_computable") or 0) * objective
                      * (1 - factor / 100))
            passes = (bool(daily.get("evaluable"))
                      and float(daily.get("uc_computables") or 0) > target)
            if passes and row.get("beneficiario"):
                person["group"] += round(group_award * 100)
                person["group_days"] += 1
            if row.get("es_polivalencia") and row.get("asistencia") == "Presente":
                person["poly"] += round(group_award * 100)
                person["poly_days"] += 1
            if row.get("aplica_grupo") and row.get("asistencia") == "Presente":
                uc = float(row.get("uc_brutas") or 0)
                eligible = [s for s in per_turn_scales[str(row["turno"])]
                            if uc >= float(s["desde_uc"])
                            and (float(s["hasta_uc"]) <= 0 or uc < float(s["hasta_uc"]))]
                if eligible:
                    person["individual"] += round(max(float(s["premio"]) for s in eligible) * 100)

        for person in person_totals.values():
            person["new"] = person["group"] + person["poly"] + person["individual"]
        totals = {field: sum(p[field] for p in person_totals.values())
                  for field in ("actual", "new", "group", "poly", "individual",
                                "group_days", "poly_days")}
        totals["less"] = sum(p["new"] < p["actual"] for p in person_totals.values())
        totals["more"] = sum(p["new"] > p["actual"] for p in person_totals.values())
        totals["same"] = len(person_totals) - totals["less"] - totals["more"]
        totals["people"] = len(person_totals)
        totals["pct"] = (100 * (totals["new"] / totals["actual"] - 1)
                         if totals["actual"] else 0)
        return totals, person_totals, per_turn_scales

    summaries = []
    for profile_key, turns in params_by_key.items():
        current_objective = float(turns[0]["uc_por_operario"])
        current_award = float(turns[0]["premio_grupal"])
        current, _, _ = compute(profile_key, current_objective, current_award, False)
        summaries.append((profile_key, turns, current_objective, current_award, current))

    above = [item for item in summaries
             if item[4]["actual"] and item[4]["pct"] > 21
             and item[0] != KNOWN_INVALID]
    results = []
    for profile_key, turns, old_objective, old_group_award, current in above:
        candidates = []
        objective_min = max(1, math.floor(old_objective * 0.65))
        objective_max = math.ceil(old_objective * 1.35)
        target_cent = round(current["actual"] * TARGET_BAG)
        for objective in range(objective_min, objective_max + 1):
            no_group, people_at_objective, scales_at_objective = compute(
                profile_key, objective, 0, True)
            individual_cent = no_group["individual"]
            events = sum(p["group_days"] + p["poly_days"]
                         for p in people_at_objective.values())
            if not events:
                continue
            center = round((target_cent - individual_cent) / (events * 10000)) * 100
            award_candidates = range(max(0, center - 300),
                                     min(int(old_group_award), center + 300) + 1, 100)
            for award in award_candidates:
                proposed, people, tranches = compute(profile_key, objective, award, True)
                if not TARGET_RANGE[0] <= proposed["pct"] <= TARGET_RANGE[1]:
                    continue
                losses = [(leg, p["new"] - p["actual"])
                          for leg, p in people.items() if p["new"] < p["actual"]]
                loss_cents = -sum(delta for _, delta in losses)
                adjustment_distance = abs(objective - old_objective) + abs(award - old_group_award) / 10
                candidates.append((len(losses), loss_cents, abs(proposed["pct"] - (TARGET_RANGE[0] + TARGET_RANGE[1]) / 2),
                                   adjustment_distance, objective, award, proposed,
                                   losses, tranches))
        if not candidates:
            results.append({"profile": profile_key, "error": "No se encontró candidato en rango."})
            continue
        best = min(candidates, key=lambda c: (c[0], c[1], c[2], c[3]))
        objective, award, proposed, losses, tranches = best[4], best[5], best[6], best[7], best[8]
        starts = [tranches[str(turns[0]["turno"])][i]["desde_uc"] for i in range(5)]
        results.append({
            "profile": profile_key,
            "current": {"objective": old_objective, "group_award": old_group_award,
                        "actual": current["actual"] / 100, "new": current["new"] / 100,
                        "increase_pct": current["pct"], "people": current["people"],
                        "more": current["more"], "less": current["less"]},
            "proposal": {"objective": objective, "group_award": award,
                         "thresholds": starts,
                         "actual": proposed["actual"] / 100, "new": proposed["new"] / 100,
                         "increase_pct": proposed["pct"], "people": proposed["people"],
                         "more": proposed["more"], "less": proposed["less"],
                         "group_and_poly": (proposed["group"] + proposed["poly"]) / 100,
                         "individual": proposed["individual"] / 100,
                         "losses": [{"legajo": leg, "difference": delta / 100}
                                    for leg, delta in losses]},
        })

    excluded = []
    for profile_key, turns, objective, award, current in summaries:
        if profile_key == KNOWN_INVALID:
            excluded.append({"profile": profile_key, "objective": objective,
                             "group_award": award, "actual": current["actual"] / 100,
                             "new": current["new"] / 100, "increase_pct": current["pct"],
                             "people": current["people"], "reason":
                             "Known incoherent group roster: Clark Congelados can pay a group award with one beneficiary.",
                             "not_adjusted": True})

    output = {"cache_calculado_at": cache["calculado_at"], "period": [FROM, TO],
              "snapshot": snapshot, "target_increase_pct": [20.0, 21.0],
              "method": "Preserves individual award amounts; simulates objective, derived UC thresholds, group award, and polyvalence from cached facts.",
              "profiles_above_21_adjusted": results, "known_exception": excluded}
    out = ROOT / "outputs" / "estimacion_ajustes_perfiles_mayor_21_20261020.json"
    out.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

