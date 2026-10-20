"""Carga diaria de TNC agrupados, independiente de las consultas de pantalla."""
import asyncio
import logging
import os
import sqlite3
import uuid
from contextlib import closing
from datetime import date, datetime, time, timedelta, timezone

from db.schema import DB_PATH
from scripts.cargar_tnc_resumen import load

logger = logging.getLogger(__name__)
ARGENTINA = timezone(timedelta(hours=-3))
START_DATE = date(2026, 10, 1)
SCHEDULE = time(5, 55)
_task = None
_stop = None


def _ensure_control(db):
    db.execute("""CREATE TABLE IF NOT EXISTS tnc_job_control (
        id INTEGER PRIMARY KEY CHECK(id = 1), owner TEXT, locked_until TEXT,
        last_success_date TEXT, last_attempt TEXT, last_error TEXT
    )""")
    db.execute("INSERT OR IGNORE INTO tnc_job_control(id) VALUES (1)")


def run_once(now=None):
    """Completa días pendientes y refresca los últimos tres días vencidos."""
    now = now or datetime.now(ARGENTINA)
    today = now.date()
    end = today - timedelta(days=1)
    if end < START_DATE:
        return 'sin_periodo'
    owner = uuid.uuid4().hex
    stamp = now.isoformat(timespec='seconds')
    lease = (now + timedelta(hours=12)).isoformat(timespec='seconds')
    with closing(sqlite3.connect(DB_PATH, timeout=30)) as db:
        _ensure_control(db)
        db.commit()
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT owner, locked_until, last_success_date FROM tnc_job_control WHERE id=1').fetchone()
        if row[2] == today.isoformat():
            db.rollback()
            return 'completo'
        if row[0] and row[1] and row[1] > stamp:
            db.rollback()
            return 'ocupado'
        db.execute('UPDATE tnc_job_control SET owner=?, locked_until=?, last_attempt=?, last_error=NULL WHERE id=1', (owner, lease, stamp))
        db.commit()
    try:
        load(START_DATE, end, refresh_from=max(START_DATE, end - timedelta(days=2)))
    except Exception as exc:
        with closing(sqlite3.connect(DB_PATH, timeout=30)) as db:
            db.execute('UPDATE tnc_job_control SET owner=NULL, locked_until=NULL, last_error=? WHERE id=1 AND owner=?', (str(exc)[:2000], owner))
            db.commit()
        raise
    with closing(sqlite3.connect(DB_PATH, timeout=30)) as db:
        db.execute('UPDATE tnc_job_control SET owner=NULL, locked_until=NULL, last_success_date=?, last_error=NULL WHERE id=1 AND owner=?', (today.isoformat(), owner))
        db.commit()
    return 'cargado'


async def _loop():
    logger.info('Scheduler TNC iniciado; ejecución diaria 05:55 hora Argentina.')
    while not _stop.is_set():
        now = datetime.now(ARGENTINA)
        if now.time().replace(tzinfo=None) >= SCHEDULE:
            try:
                result = await asyncio.to_thread(run_once, now)
                if result == 'cargado':
                    logger.info('TNC: carga completada hasta %s.', now.date() - timedelta(days=1))
            except Exception:
                logger.exception('TNC: carga fallida; se reintentará en 15 minutos.')
                try:
                    await asyncio.wait_for(_stop.wait(), timeout=900)
                except asyncio.TimeoutError:
                    pass
                continue
        try:
            await asyncio.wait_for(_stop.wait(), timeout=60)
        except asyncio.TimeoutError:
            pass


def start_tnc_scheduler():
    global _task, _stop
    environment = os.getenv('VIGIA_APP_ENV', 'test').strip().lower()
    if environment not in {'prod', 'production', 'produccion'}:
        logger.info('Scheduler TNC deshabilitado en entorno %s.', environment)
        return
    if os.getenv('TNC_SCHEDULER_ENABLED', '1').strip().lower() not in {'1', 'true', 'yes', 'on'}:
        logger.info('Scheduler TNC deshabilitado.')
        return
    if _task and not _task.done():
        return
    _stop = asyncio.Event()
    _task = asyncio.create_task(_loop())


async def stop_tnc_scheduler():
    global _task, _stop
    if _stop:
        _stop.set()
    if _task:
        await _task
    _task = _stop = None
