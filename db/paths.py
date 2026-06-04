"""Resolucion centralizada de rutas para las bases SQLite de VigIA."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")


def _expanded_path(value: str) -> Path:
    return Path(os.path.expandvars(value)).expanduser()


def resolve_db_path(env_name: str, filename: str, legacy_dir: Path) -> Path:
    """Resuelve una base por override individual, carpeta comun o ubicacion historica."""
    configured = os.getenv(env_name, "").strip()
    if configured:
        path = _expanded_path(configured)
        return path if path.suffix.lower() == ".db" else path / filename

    common_dir = os.getenv("VIGIA_DB_DIR", "").strip()
    if common_dir:
        return _expanded_path(common_dir) / filename

    return legacy_dir / filename
