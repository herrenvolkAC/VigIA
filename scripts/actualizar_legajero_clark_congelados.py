"""Applies the RRHH-validated Clark Congelados roster to the local profile override.

The source RRHH legajero (vigia.db) remains untouched. This auditable override
is consumed by the productivity calculation layer and is followed by a full
Aug-Sep group and individual recalculation.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAB = ROOT / "datos" / "laboratorio_premios.db"
RRHH = ROOT / "datos" / "vigia.db"
PERIOD = ("2026-08-01", "2026-09-30")
SOURCE = "Nómina operativa de Clark Congelados aportada por RRHH el 2026-10-22."
ROSTER = {
    "86039": "DIAZ CARLOS ALEJANDRO",
    "89963": "FLORES MATIAS MAXIMILIANO",
    "103999": "CARMONA CRISTIAN DAVID",
    "109203": "VERON MATIAS GABRIEL",
    "121583": "VUJOVICH SEBASTIAN MIGUEL ALEJANDRO",
}


def update_profiles() -> str:
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    rrhh = sqlite3.connect(f"file:{RRHH}?mode=ro", uri=True)
    try:
        found = {str(r[0]).strip(): str(r[1]).strip() for r in rrhh.execute(
            "SELECT legajo,nombre FROM rrhh_personas WHERE legajo IN (?,?,?,?,?)",
            tuple(ROSTER),
        )}
    finally:
        rrhh.close()
    if found != ROSTER:
        raise RuntimeError(f"La nómina local no coincide con la evidencia: {found!r}")

    con = sqlite3.connect(LAB, timeout=60)
    try:
        con.execute("PRAGMA busy_timeout=60000")
        con.execute("BEGIN IMMEDIATE")
        con.execute("""CREATE TABLE IF NOT EXISTS lab_perfil_operativo_legajo_audit(
            run_id TEXT NOT NULL, legajo TEXT NOT NULL, perfil_anterior_json TEXT,
            perfil_nuevo_json TEXT NOT NULL, fuente TEXT NOT NULL,
            changed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(run_id,legajo))""")
        for legajo, nombre in ROSTER.items():
            old = con.execute(
                "SELECT legajo,sector,funcion_legajero,motivo,activo FROM lab_perfil_operativo_legajo WHERE legajo=?",
                (legajo,),
            ).fetchone()
            new = {
                "legajo": legajo,
                "nombre": nombre,
                "sector": "CD-REFRIGERADOS",
                "funcion_legajero": "CLARK CONGELADOS",
                "motivo": SOURCE,
                "activo": 1,
            }
            con.execute(
                "INSERT INTO lab_perfil_operativo_legajo_audit "
                "(run_id,legajo,perfil_anterior_json,perfil_nuevo_json,fuente) VALUES(?,?,?,?,?)",
                (run_id, legajo, json.dumps(old, ensure_ascii=False) if old else None,
                 json.dumps(new, ensure_ascii=False), SOURCE),
            )
            con.execute("""INSERT INTO lab_perfil_operativo_legajo
                (legajo,sector,funcion_legajero,motivo,activo,updated_at)
                VALUES(?,?,?,?,1,CURRENT_TIMESTAMP)
                ON CONFLICT(legajo) DO UPDATE SET
                    sector=excluded.sector,
                    funcion_legajero=excluded.funcion_legajero,
                    motivo=excluded.motivo,
                    activo=1,
                    updated_at=CURRENT_TIMESTAMP""",
                (legajo, new["sector"], new["funcion_legajero"], new["motivo"]),
            )
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    return run_id


async def main() -> None:
    run_id = update_profiles()
    sys.path.insert(0, str(ROOT))
    import routers.estudio_premios_productividad as estudio

    async def admin_local(_request):
        return {"role": "admin", "device_status": "approved"}

    estudio._admin = admin_local
    grupal = await estudio.calculo_grupal(None, *PERIOD)
    individual = await estudio.recalcular_individual(None, *PERIOD)
    print(json.dumps({
        "ok": True,
        "run_id": run_id,
        "period": PERIOD,
        "legajos": list(ROSTER),
        "group_rows": len(grupal.get("nivel_3", [])),
        "individual": individual,
    }, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
