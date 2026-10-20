"""Simula montos sin modificar parámetros, caches ni la presentación."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "outputs/informe_gerencial_umbrales_65_20261019.json"

FAMILIES = {
    "ARMADO": {"perfil-1", "perfil-5", "perfil-8", "perfil-11", "perfil-12"},
    "CLARK": {"perfil-2", "perfil-6", "perfil-9", "perfil-13", "perfil-14"},
    "RECEPCION": {"perfil-4", "perfil-7", "perfil-10", "perfil-16"},
    "CARGA": {"perfil-3", "perfil-15"},
    "CONTROL": {"perfil-17"},
}


def rounded(value: float) -> int:
    return int(round(value / 100.0) * 100)


def persons(profile):
    result = []
    for person in profile["piloto_legajos"]:
        rows = person["dias"]
        result.append({
            "legajo": person["legajo"],
            "actual": sum(r["actual"] for r in rows),
            "group_days": sum(r["grupal"] > 0 for r in rows),
            "poly_days": sum(r["polivalencia"] > 0 for r in rows),
            "levels": {level: sum(r["individual"] > 0 and r["nivel"] == level for r in rows)
                       for level in range(1, 6)},
        })
    return result


def simulate(target: float, report: dict, balanced: bool = False):
    profiles = {p["id"]: p for p in report["perfiles"]}
    result = {"objetivo": target, "criterio": "balanceado" if balanced else "minimiza_bajas", "familias": {}}
    all_people = []
    for family, ids in FAMILIES.items():
        population = []
        group_current = individual_current = actual = 0
        for pid in ids:
            p = profiles[pid]
            pp = persons(p)
            population.extend((p, x) for x in pp)
            actual += sum(x["actual"] for x in pp)
            group_current += sum((x["group_days"] + x["poly_days"]) * p["premio_grupal"] * 100 for x in pp)
            awards = {s["nivel"]: s["premio"] for s in p["escala_individual"]}
            individual_current += sum(sum(x["levels"][level] * awards[level] * 100 for level in range(1, 6)) for x in pp)
        candidates = []
        for step in range(10, 301):
            group_factor = step / 100
            individual_factor = ((actual * target) - group_current * group_factor) / individual_current if individual_current else 0
            if not .10 <= individual_factor <= 3:
                continue
            if balanced and not (.30 <= group_factor <= 2 and .30 <= individual_factor <= 2
                                 and .50 <= group_factor / individual_factor <= 2):
                continue
            diffs = []
            for p, x in population:
                new = (x["group_days"] + x["poly_days"]) * p["premio_grupal"] * 100 * group_factor
                awards = {s["nivel"]: s["premio"] for s in p["escala_individual"]}
                new += sum(x["levels"][level] * awards[level] * 100 * individual_factor for level in range(1, 6))
                diffs.append(new - x["actual"])
            more = sum(v > .5 for v in diffs)
            less = sum(v < -.5 for v in diffs)
            candidates.append((less, -more, abs(group_factor-individual_factor),
                               abs(group_factor-1)+abs(individual_factor-1),
                               group_factor, individual_factor))
        _, _, _, _, gf, inf = min(candidates)
        settings = {}
        family_people = []
        for pid in sorted(ids):
            p = profiles[pid]
            group_award = rounded(p["premio_grupal"] * gf)
            individual_awards = {s["nivel"]: rounded(s["premio"] * inf) for s in p["escala_individual"]}
            settings[pid] = {"sector": p["sector"], "funcion": p["funcion"],
                             "grupal": group_award, "individual": individual_awards}
            for x in persons(p):
                new = (x["group_days"] + x["poly_days"]) * group_award * 100
                new += sum(x["levels"][level] * individual_awards[level] * 100 for level in range(1, 6))
                family_people.append((x["actual"], new))
                all_people.append((x["actual"], new))
        result["familias"][family] = {
            "factor_grupal": gf, "factor_individual": inf,
            "actual": sum(x[0] for x in family_people) / 100,
            "nuevo": sum(x[1] for x in family_people) / 100,
            "mas": sum(x[1] > x[0] for x in family_people),
            "menos": sum(x[1] < x[0] for x in family_people),
            "igual": sum(x[1] == x[0] for x in family_people),
            "montos": settings,
        }
    actual = sum(x[0] for x in all_people)
    new = sum(x[1] for x in all_people)
    result["total"] = {"actual": actual/100, "nuevo": new/100,
                       "variacion_pct": (new/actual-1)*100,
                       "mas": sum(x[1] > x[0] for x in all_people),
                       "menos": sum(x[1] < x[0] for x in all_people),
                       "igual": sum(x[1] == x[0] for x in all_people)}
    return result


if __name__ == "__main__":
    data = json.loads(REPORT.read_text(encoding="utf-8"))
    output = ([simulate(target, data) for target in (1.10, 1.125, 1.15)]
              + [simulate(target, data, balanced=True) for target in (1.10, 1.125, 1.15)])
    path = ROOT / "outputs/escenarios_montos_10_15.json"
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps([{"objetivo": x["objetivo"], **x["total"]} for x in output], ensure_ascii=False, indent=2))
