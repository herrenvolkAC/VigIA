"""Ajusta premios vigentes para una bolsa total objetivo de +10% vs pago actual.

Escala montos grupales e individuales de forma proporcional, redondeando cada
valor configurado al centenar. Deja auditoría local antes de mutar y recalcula
agosto-septiembre 2026 antes de exportar el HTML gerencial.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
import json
import math
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import routers.estudio_premios_productividad as estudio
from generar_informe_gerencial_umbrales import analyze, attach_polivalency_summaries, render

PERIOD = ("2026-08-01", "2026-09-30")
DB_PATH = ROOT / "datos" / "laboratorio_premios.db"
HTML_PATH = ROOT / "outputs" / "informe_gerencial_bolsa_mas10_20261021.html"
JSON_PATH = HTML_PATH.with_suffix(".json")
TARGET_PCT = 10.0
ROUNDING = 100.0  # montos configurados se expresan en múltiplos de $100


async def admin_local(_request):
    return {"role": "admin", "device_status": "approved"}


def rounded_award_cents(cents: int, factor: float) -> int:
    dollars = cents / 100
    adjusted = math.floor(dollars * factor / ROUNDING + 0.5) * ROUNDING
    return int(adjusted * 100)


def choose_factor(report: dict) -> tuple[float, int, int, int]:
    actual = sum(p["actual_centavos"] for p in report["perfiles"])
    current_new = sum(p["nuevo_centavos"] for p in report["perfiles"])
    target = math.floor(actual * (1 + TARGET_PCT / 100) + 0.5)
    events = [d for p in report["perfiles"] for person in p.get("piloto_legajos", [])
              for d in person.get("dias", [])]

    def projected(factor: float) -> int:
        return sum(rounded_award_cents(d.get("grupal", 0), factor)
                   + rounded_award_cents(d.get("individual", 0), factor)
                   + rounded_award_cents(d.get("polivalencia", 0), factor)
                   for d in events)

    low, high = 0.0, max(2.0, target / max(current_new, 1) * 2)
    for _ in range(64):
        mid = (low + high) / 2
        if projected(mid) < target:
            low = mid
        else:
            high = mid
    candidates = {low, high, (low + high) / 2}
    factor = min(candidates, key=lambda f: abs(projected(f) - target))
    return factor, actual, current_new, projected(factor)


def update_awards(factor: float, audit_id: str) -> dict:
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    try:
        db.execute("BEGIN IMMEDIATE")
        params = [dict(r) for r in db.execute(
            "SELECT * FROM lab_parametro_grupal WHERE activo=1 ORDER BY sector,funcion_legajero,turno")]
        scales = [dict(r) for r in db.execute(
            "SELECT * FROM lab_escala_individual_grupal WHERE activo=1 ORDER BY sector,funcion_legajero,turno,operacion_medible,division_madre,nivel")]
        if not params or not scales:
            raise RuntimeError("No se encontraron parámetros y escalas activos.")
        db.execute("INSERT INTO lab_ajuste_umbral_auditoria(ejecucion,tipo,payload_json) VALUES(?,?,?)",
                   (audit_id, "bolsa_mas10_parametros_antes", json.dumps(params, ensure_ascii=False)))
        db.execute("INSERT INTO lab_ajuste_umbral_auditoria(ejecucion,tipo,payload_json) VALUES(?,?,?)",
                   (audit_id, "bolsa_mas10_escalas_antes", json.dumps(scales, ensure_ascii=False)))
        db.execute("INSERT INTO lab_ajuste_umbral_auditoria(ejecucion,tipo,payload_json) VALUES(?,?,?)",
                   (audit_id, "bolsa_mas10_factor_y_criterio", json.dumps({
                       "factor": factor, "objetivo": "+10% sobre pago actual total",
                       "distribucion": "factor proporcional común a grupal e individual; polivalencia sigue igual al grupal",
                       "redondeo": "$100 por valor diario", "periodo": PERIOD,
                   }, ensure_ascii=False)))
        cur_p = db.execute("UPDATE lab_parametro_grupal SET premio_grupal=CAST(ROUND(premio_grupal * ? / ?,0) * ? AS REAL), updated_at=CURRENT_TIMESTAMP WHERE activo=1",
                           (factor, ROUNDING, ROUNDING))
        cur_s = db.execute("UPDATE lab_escala_individual_grupal SET premio=CAST(ROUND(premio * ? / ?,0) * ? AS REAL), updated_at=CURRENT_TIMESTAMP WHERE activo=1",
                           (factor, ROUNDING, ROUNDING))
        db.commit()
        return {"parametros_actualizados": cur_p.rowcount, "escalas_actualizadas": cur_s.rowcount}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


async def main() -> None:
    estudio._admin = admin_local
    before = analyze(*PERIOD)
    factor, actual, current_new, projected = choose_factor(before)
    execution = datetime.now().astimezone().isoformat(timespec="seconds")
    updates = update_awards(factor, execution)

    # Rebuild both internal result caches from the new configured awards.
    group = await estudio.calculo_grupal(None, *PERIOD)
    individual = await estudio.recalcular_individual(None, *PERIOD)
    report = analyze(*PERIOD)
    attach_polivalency_summaries(report)
    if len(report["perfiles"]) != 17 or report["dias"] != 43:
        raise RuntimeError(f"Validación de alcance fallida: {len(report['perfiles'])} perfiles / {report['dias']} días")
    total_actual = sum(p["actual_centavos"] for p in report["perfiles"])
    total_new = sum(p["nuevo_centavos"] for p in report["perfiles"])
    variance = (total_new / total_actual - 1) * 100 if total_actual else 0
    if not 9.5 <= variance <= 10.5:
        raise RuntimeError(f"El resultado quedó fuera de tolerancia: +{variance:.3f}%")

    report["escenario_bolsa"] = {
        "objetivo_pct": TARGET_PCT, "factor_montos": factor,
        "pago_actual_centavos": total_actual, "pago_nuevo_centavos": total_new,
        "variacion_pct": variance, "redondeo": "$100 por valor configurado",
        "distribucion": "Factor proporcional común a premios grupales e individuales; polivalencia conserva el valor grupal.",
        "calculado_at": execution,
    }
    HTML_PATH.parent.mkdir(parents=True, exist_ok=True)
    html = render(report)
    banner = (f'<div class="scenario-banner"><strong>Escenario de distribución de bolsa</strong>'
              f'<span>Pago nuevo: +{variance:.1f}% frente al actual · Factor aplicado: {factor:.4f} · '
              f'Premios grupales e individuales ajustados proporcionalmente; polivalencia mantiene el valor grupal.</span></div>')
    html = html.replace("<main>", "<main>" + banner, 1)
    html = html.replace("</style>", ".scenario-banner{max-width:1240px;margin:10px auto 0;padding:12px 18px;border-left:5px solid #13748b;background:#e5f2f4;color:#142f42;display:flex;gap:14px;align-items:center;font:14px/1.4 Segoe UI,Arial,sans-serif}.scenario-banner strong{white-space:nowrap}.scenario-banner span{color:#405b69}@media print{.scenario-banner{margin:0 auto 8px;max-width:none}}\n</style>", 1)
    HTML_PATH.write_text(html, encoding="utf-8")
    JSON_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "ok": True, "auditoria": execution, "periodo": PERIOD, "dias_laborables": report["dias"],
        "perfiles": len(report["perfiles"]), "factor_aplicado": factor,
        "factor_estimado_antes_redondeo": (actual * 1.1 / current_new),
        "total_actual": total_actual / 100, "total_nuevo": total_new / 100,
        "diferencia": (total_new - total_actual) / 100, "variacion_pct": variance,
        "proyeccion_antes_recalculo": projected / 100,
        "filas_grupo": len(group.get("nivel_2", [])), "filas_legajo_dia": len(group.get("nivel_3", [])),
        "individual": individual, "filas_configuracion": updates,
        "html": str(HTML_PATH), "json": str(JSON_PATH),
    }, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
