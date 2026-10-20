"""Recalculate Aug-Sep 2026 award caches and export the current management deck."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import routers.estudio_premios_productividad as estudio
from generar_informe_gerencial_umbrales import analyze, attach_polivalency_summaries, render

PERIOD = ("2026-08-01", "2026-09-30")
OUTPUT = ROOT / "outputs" / "informe_gerencial_premios_actualizado_20261020.html"


async def admin_local(_request):
    return {"role": "admin", "device_status": "approved"}


async def main() -> None:
    estudio._admin = admin_local
    group = await estudio.calculo_grupal(None, *PERIOD)
    individual = await estudio.recalcular_individual(None, *PERIOD)
    report = analyze(*PERIOD)
    attach_polivalency_summaries(report)
    if len(report["perfiles"]) != 17:
        raise RuntimeError(f"Se esperaban 17 perfiles; el informe contiene {len(report['perfiles'])}.")
    if any(profile["con_base"] and profile["dias"] != report["dias"]
           for profile in report["perfiles"]):
        raise RuntimeError("El informe tiene períodos inconsistentes entre perfiles.")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(render(report), encoding="utf-8")
    OUTPUT.with_suffix(".json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    total_actual = sum(profile["actual_centavos"] for profile in report["perfiles"])
    total_new = sum(profile["nuevo_centavos"] for profile in report["perfiles"])
    payload = {
        "ok": True,
        "periodo": PERIOD,
        "dias_laborables": report["dias"],
        "perfiles": len(report["perfiles"]),
        "cache_grupal_calculado_at": report["cache_grupal"],
        "snapshot_pago_actual": report["snapshot_pagos"],
        "grupos_diarios": len(group.get("nivel_2", [])),
        "legajo_dias": len(group.get("nivel_3", [])),
        "individual": individual,
        "pago_actual_perfiles_centavos": total_actual,
        "pago_nuevo_perfiles_centavos": total_new,
        "variacion_pct": (100 * (total_new / total_actual - 1) if total_actual else 0),
        "html": str(OUTPUT),
        "json": str(OUTPUT.with_suffix(".json")),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
