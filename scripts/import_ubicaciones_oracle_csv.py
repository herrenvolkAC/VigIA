"""
Importa un snapshot CSV de F005UBIA a vigia.db para uso local en desarrollo.

Uso:
    python scripts/import_ubicaciones_oracle_csv.py --csv C:\\ruta\\F005UBIA.csv
"""
import argparse
import asyncio
import csv
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from db.schema import DB_PATH, init_db  # noqa: E402


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Importa F005UBIA CSV a SQLite")
    parser.add_argument("--csv", required=True, help="Ruta absoluta al CSV exportado desde Oracle")
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Borra el snapshot actual antes de importar. Default: true",
    )
    return parser.parse_args()


def _safe_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _safe_int(value: str | None) -> int | None:
    text = _safe_text(value)
    if text is None:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _safe_float(value: str | None) -> float | None:
    text = _safe_text(value)
    if text is None:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _ubicacion_codigo(cpasillo: str | None, chuecopa: int | None, nposlarg: int | None) -> str:
    pasillo = _safe_text(cpasillo) or ""
    hueco = f"{int(chuecopa):03d}" if chuecopa is not None else ""
    pos = str(int(nposlarg)) if nposlarg is not None else ""
    return f"{pasillo}{hueco}{pos}"


def _ubicacion_id(czonalma: str | None, cpasillo: str | None, chuecopa: int | None, nposlarg: int | None, nnivelal: int | None, xtipsubi: str | None) -> str:
    return "|".join(
        [
            _safe_text(czonalma) or "",
            _safe_text(cpasillo) or "",
            str(chuecopa or ""),
            str(nposlarg or ""),
            str(nnivelal or ""),
            _safe_text(xtipsubi) or "",
        ]
    )


async def _import_csv(csv_path: Path, replace: bool) -> tuple[int, int]:
    import aiosqlite

    inserted = 0
    skipped = 0
    async with aiosqlite.connect(DB_PATH) as db:
        if replace:
            await db.execute("DELETE FROM ubicaciones_oracle")

        with csv_path.open("r", encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            for raw in reader:
                czonalma = _safe_text(raw.get("CZONALMA"))
                cpasillo = _safe_text(raw.get("CPASILLO"))
                chuecopa = _safe_int(raw.get("CHUECOPA"))
                nnivelal = _safe_int(raw.get("NNIVELAL"))
                nposlarg = _safe_int(raw.get("NPOSLARG"))
                xtipsubi = _safe_text(raw.get("XTIPSUBI"))
                ubicacion_codigo = _ubicacion_codigo(cpasillo, chuecopa, nposlarg)
                ubicacion_id = _ubicacion_id(czonalma, cpasillo, chuecopa, nposlarg, nnivelal, xtipsubi)

                if not (czonalma and cpasillo and chuecopa is not None and ubicacion_codigo):
                    skipped += 1
                    continue

                await db.execute(
                    """
                    INSERT OR REPLACE INTO ubicaciones_oracle (
                        ubicacion_id, snapshot_source, cempresa, calmacen, czonalma, cpasillo,
                        chuecopa, cdigcont, nnivelal, nposlarg, cumdimen, qaltubic, qancubic,
                        qlarubic, cunmpeso, qpmaxubi, cumvolum, qvmaxubi, xpropubi, xtipsubi,
                        xubilimi, fultrecu, copultre, xsitubic, xblqrecu, cconsign, qpalaltu,
                        qpalprof, crotacio, qpesoact, qvoluact, qpalactu, xsetrasp, xserotos,
                        fcreareg, fmodireg, copecrea, codinuti, pasifisi, ggercome, qpemaxpa,
                        qaltubpi, ubicacion_codigo
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                    """,
                    (
                        ubicacion_id,
                        str(csv_path),
                        _safe_text(raw.get("CEMPRESA")),
                        _safe_text(raw.get("CALMACEN")),
                        czonalma,
                        cpasillo,
                        chuecopa,
                        _safe_text(raw.get("CDIGCONT")),
                        nnivelal,
                        nposlarg,
                        _safe_text(raw.get("CUMDIMEN")),
                        _safe_float(raw.get("QALTUBIC")),
                        _safe_float(raw.get("QANCUBIC")),
                        _safe_float(raw.get("QLARUBIC")),
                        _safe_text(raw.get("CUNMPESO")),
                        _safe_float(raw.get("QPMAXUBI")),
                        _safe_text(raw.get("CUMVOLUM")),
                        _safe_float(raw.get("QVMAXUBI")),
                        _safe_text(raw.get("XPROPUBI")),
                        xtipsubi,
                        _safe_text(raw.get("XUBILIMI")),
                        _safe_text(raw.get("FULTRECU")),
                        _safe_text(raw.get("COPULTRE")),
                        _safe_text(raw.get("XSITUBIC")),
                        _safe_text(raw.get("XBLQRECU")),
                        _safe_text(raw.get("CCONSIGN")),
                        _safe_float(raw.get("QPALALTU")),
                        _safe_float(raw.get("QPALPROF")),
                        _safe_text(raw.get("CROTACIO")),
                        _safe_float(raw.get("QPESOACT")),
                        _safe_float(raw.get("QVOLUACT")),
                        _safe_float(raw.get("QPALACTU")),
                        _safe_text(raw.get("XSETRASP")),
                        _safe_text(raw.get("XSEROTOS")),
                        _safe_text(raw.get("FCREAREG")),
                        _safe_text(raw.get("FMODIREG")),
                        _safe_text(raw.get("COPECREA")),
                        _safe_text(raw.get("CODINUTI")),
                        _safe_text(raw.get("PASIFISI")),
                        _safe_text(raw.get("GGERCOME")),
                        _safe_float(raw.get("QPEMAXPA")),
                        _safe_float(raw.get("QALTUBPI")),
                        ubicacion_codigo,
                    ),
                )
                inserted += 1

        await db.commit()

    return inserted, skipped


async def main() -> int:
    load_dotenv(dotenv_path=ROOT_DIR / ".env", override=True)
    args = _parse_args()
    csv_path = Path(args.csv)
    if not csv_path.exists():
        print(f"[ERROR] No existe el CSV: {csv_path}")
        return 1

    await init_db()
    inserted, skipped = await _import_csv(csv_path, replace=True)
    print(f"[OK] ubicaciones_oracle cargada desde: {csv_path}")
    print(f"[OK] Registros insertados: {inserted}")
    print(f"[OK] Registros omitidos: {skipped}")
    print(f"[OK] Base destino: {DB_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
