from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import tempfile
import zipfile
from contextlib import closing
from datetime import datetime, time
from pathlib import Path
from typing import Any

from db.auth import AUTH_DB_PATH
from db.checklist_tareas import CHECKLIST_DB_PATH
from db.daily_auto import DAILY_AUTO_DB_PATH
from db.daily_operativa import DAILY_DB_PATH
from db.panol_insumos import PANOL_DB_PATH
from db.plantel_optimo import PLANTEL_OPTIMO_DB_PATH
from db.schema import DB_PATH
from routers.analisis_premio_productividad import PREMIO_DB_PATH
from routers.simulador_operativo import SIMULADOR_DB_PATH
from utils.usage_log import write_usage_event


logger = logging.getLogger("vigia.db_backup")

_backup_task: asyncio.Task | None = None
_backup_stop: asyncio.Event | None = None
_backup_running = False


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "si", "on"}


def _backup_dir() -> Path | None:
    configured = os.getenv("VIGIA_DB_BACKUP_DIR", "").strip()
    if not configured:
        return None
    return Path(os.path.expandvars(configured)).expanduser()


def _backup_enabled() -> bool:
    return _env_bool("VIGIA_DB_BACKUP_ENABLED", _backup_dir() is not None)


def _backup_time() -> time:
    raw = os.getenv("VIGIA_DB_BACKUP_TIME", "02:00").strip()
    try:
        hour, minute = raw.split(":", 1)
        return time(int(hour), int(minute))
    except Exception:
        logger.warning("[db-backup] Hora invalida %r; se usa 02:00.", raw)
        return time(2, 0)


def _backup_zip_name() -> str:
    return os.getenv("VIGIA_DB_BACKUP_ZIP_NAME", "VigIA_DB_Backup.zip").strip() or "VigIA_DB_Backup.zip"


def _sqlite_timeout_seconds() -> float:
    try:
        return max(float(os.getenv("VIGIA_DB_BACKUP_SQLITE_TIMEOUT_SECONDS", "30")), 1.0)
    except ValueError:
        return 30.0


def _compress_level() -> int:
    try:
        return min(max(int(os.getenv("VIGIA_DB_BACKUP_COMPRESS_LEVEL", "6")), 0), 9)
    except ValueError:
        return 6


def _mb(size_bytes: int | float) -> str:
    return f"{float(size_bytes) / (1024 * 1024):.1f} MB"


def _log_backup_usage(action_text: str) -> None:
    try:
        write_usage_event("sistema", "servidor", "sistema", action_text, action="backup", attention=True)
    except Exception:
        logger.debug("[db-backup] No se pudo escribir en VigiaLog.", exc_info=True)


def configured_db_paths() -> list[tuple[str, Path]]:
    candidates = [
        ("vigia.db", DB_PATH),
        ("vigia_auth.db", AUTH_DB_PATH),
        ("checklist_tareas.db", CHECKLIST_DB_PATH),
        ("daily_operativa.db", DAILY_DB_PATH),
        ("daily_auto.db", DAILY_AUTO_DB_PATH),
        ("panol_insumos.db", PANOL_DB_PATH),
        ("plantel_optimo.db", PLANTEL_OPTIMO_DB_PATH),
        ("premio_productividad.db", PREMIO_DB_PATH),
        ("simulador_operativo.db", SIMULADOR_DB_PATH),
    ]
    seen: set[Path] = set()
    result: list[tuple[str, Path]] = []
    for name, path in candidates:
        resolved = Path(path).resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        result.append((name, resolved))
    return result


def _backup_sqlite_db(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_uri = f"{source.resolve().as_uri()}?mode=ro"
    timeout = _sqlite_timeout_seconds()
    with closing(sqlite3.connect(source_uri, uri=True, timeout=timeout)) as src:
        with closing(sqlite3.connect(destination, timeout=timeout)) as dst:
            src.backup(dst, pages=1000, sleep=0.05)


def run_db_backup_once(*, force: bool = False) -> dict[str, Any]:
    global _backup_running
    if _backup_running:
        return {"ok": False, "skipped": True, "reason": "Backup en ejecucion."}

    target_dir = _backup_dir()
    if not target_dir:
        return {"ok": False, "skipped": True, "reason": "VIGIA_DB_BACKUP_DIR no configurado."}

    target_dir.mkdir(parents=True, exist_ok=True)
    marker_path = target_dir / "VigIA_DB_Backup.last"
    today = datetime.now().strftime("%Y-%m-%d")
    if marker_path.exists() and not force:
        last = marker_path.read_text(encoding="utf-8", errors="ignore").strip().splitlines()
        if last and last[0] == today:
            return {"ok": True, "skipped": True, "reason": "Backup diario ya ejecutado.", "date": today}

    zip_path = target_dir / _backup_zip_name()
    tmp_zip_path = zip_path.with_suffix(zip_path.suffix + ".tmp")
    backup_started = datetime.now()
    dbs = configured_db_paths()
    included: list[dict[str, Any]] = []
    missing: list[dict[str, str]] = []

    _backup_running = True
    try:
        if tmp_zip_path.exists():
            tmp_zip_path.unlink()
        with tempfile.TemporaryDirectory(prefix="vigia_db_backup_") as tmp_dir_raw:
            tmp_dir = Path(tmp_dir_raw)
            compression = zipfile.ZIP_STORED if _compress_level() == 0 else zipfile.ZIP_DEFLATED
            with zipfile.ZipFile(
                tmp_zip_path,
                "w",
                compression=compression,
                compresslevel=None if compression == zipfile.ZIP_STORED else _compress_level(),
                allowZip64=True,
            ) as archive:
                for logical_name, source in dbs:
                    if not source.exists():
                        missing.append({"name": logical_name, "path": str(source)})
                        continue
                    temp_db = tmp_dir / logical_name
                    _backup_sqlite_db(source, temp_db)
                    archive.write(temp_db, arcname=f"db/{logical_name}")
                    included.append(
                        {
                            "name": logical_name,
                            "path": str(source),
                            "size_bytes": source.stat().st_size,
                            "backup_size_bytes": temp_db.stat().st_size,
                        }
                    )
                    temp_db.unlink(missing_ok=True)
                if not included:
                    raise RuntimeError("No se encontro ninguna base SQLite configurada para respaldar.")
                manifest = {
                    "app": "VigIA",
                    "started_at": backup_started.isoformat(timespec="seconds"),
                    "finished_at": datetime.now().isoformat(timespec="seconds"),
                    "included": included,
                    "missing": missing,
                }
                archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))

        os.replace(tmp_zip_path, zip_path)
        marker_path.write_text(today, encoding="utf-8")
        result = {
            "ok": True,
            "skipped": False,
            "date": today,
            "zip_path": str(zip_path),
            "zip_size_bytes": zip_path.stat().st_size,
            "included_count": len(included),
            "missing_count": len(missing),
            "included": included,
            "missing": missing,
        }
        logger.info(
            "[db-backup] Backup OK: %s bases, %s omitidas, archivo=%s, tamano=%s bytes.",
            len(included),
            len(missing),
            zip_path,
            result["zip_size_bytes"],
        )
        _log_backup_usage(
            "Backup de bases realizado. "
            f"Archivo: {zip_path.name}. "
            f"Bases incluidas: {len(included)}. "
            f"Bases omitidas: {len(missing)}. "
            f"Tamano comprimido: {_mb(result['zip_size_bytes'])}."
        )
        return result
    except Exception:
        if tmp_zip_path.exists():
            tmp_zip_path.unlink(missing_ok=True)
        logger.exception("[db-backup] Fallo el backup; se conserva el zip anterior si existia.")
        _log_backup_usage("No se pudo realizar el backup de bases. Se conserva el backup anterior.")
        raise
    finally:
        _backup_running = False


async def _backup_scheduler_loop() -> None:
    assert _backup_stop is not None
    logger.info("[db-backup] Scheduler iniciado. Hora diaria: %s.", _backup_time().strftime("%H:%M"))
    while not _backup_stop.is_set():
        try:
            if _backup_enabled() and datetime.now().time() >= _backup_time():
                result = await asyncio.to_thread(run_db_backup_once)
                if result.get("skipped"):
                    logger.debug("[db-backup] %s", result.get("reason"))
            elif not _backup_enabled():
                logger.debug("[db-backup] Deshabilitado o sin VIGIA_DB_BACKUP_DIR.")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("[db-backup] No se pudo ejecutar backup: %s", exc)

        try:
            await asyncio.wait_for(_backup_stop.wait(), timeout=300)
        except asyncio.TimeoutError:
            pass
    logger.info("[db-backup] Scheduler detenido.")


def start_db_backup_scheduler() -> None:
    global _backup_task, _backup_stop
    if _backup_task and not _backup_task.done():
        return
    _backup_stop = asyncio.Event()
    _backup_task = asyncio.create_task(_backup_scheduler_loop())


async def stop_db_backup_scheduler() -> None:
    global _backup_task, _backup_stop
    if _backup_stop:
        _backup_stop.set()
    if _backup_task:
        _backup_task.cancel()
        try:
            await _backup_task
        except asyncio.CancelledError:
            pass
    _backup_task = None
    _backup_stop = None
