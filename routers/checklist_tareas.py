"""API del modulo CheckList Tareas."""
from __future__ import annotations

import io
import json
from datetime import date, datetime, timedelta
from typing import Any, Literal

import aiosqlite
import xlsxwriter
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from db.auth import auth_db
from db.checklist_tareas import checklist_db, now_iso
from routers.auth_local import current_auth, user_has_module_access


router = APIRouter(prefix="/api/checklist-tareas", tags=["checklist-tareas"])
WEEKDAYS = ["Lunes", "Martes", "Miercoles", "Jueves", "Viernes", "Sabado", "Domingo"]
VALID_STATUSES = {"pending", "completed", "not_applicable"}


class OccurrenceActionRequest(BaseModel):
    action: Literal["complete", "pending", "not_applicable", "reprogram"]
    effective_date: str | None = None
    note: str = ""
    version: int | None = None


class OccurrenceReference(BaseModel):
    assignment_id: int
    scheduled_date: str
    version: int | None = None


class GroupOccurrenceActionRequest(BaseModel):
    action: Literal["complete", "pending", "not_applicable", "reprogram"]
    effective_date: str | None = None
    note: str = ""
    items: list[OccurrenceReference] = Field(default_factory=list, min_length=1)


class EventualRequest(BaseModel):
    title: str
    date: str
    username: str
    duration_minutes: int | None = Field(default=None, ge=0, le=1440)
    allow_delay: bool = False


class TaskRequest(BaseModel):
    title: str
    description: str = ""
    duration_minutes: int | None = Field(default=None, ge=0, le=1440)
    active: bool = True


class ScheduleRequest(BaseModel):
    type: Literal["weekly", "specific_date", "monthly_day"] | None = None
    weekdays: list[int] = Field(default_factory=list)
    date: str | None = None
    day: int | None = Field(default=None, ge=1, le=31)


class AssignmentRequest(BaseModel):
    task_id: int
    username: str
    allow_delay: bool = False
    instructions_override: str = ""
    active: bool = True
    schedule: ScheduleRequest = Field(default_factory=ScheduleRequest)


class DelegationAssignmentRequest(BaseModel):
    assignment_id: int
    to_username: str


class DelegationRequest(BaseModel):
    from_username: str
    date_from: str
    date_to: str
    assignments: list[DelegationAssignmentRequest] = Field(default_factory=list, min_length=1)


def _iso_date(value: str, field: str = "fecha") -> str:
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"{field} invalida.") from exc


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


async def _require_user(request: Request) -> dict[str, Any]:
    auth = await current_auth(request)
    if not auth:
        raise HTTPException(status_code=401, detail="No autenticado.")
    if auth.get("device_status") != "approved":
        raise HTTPException(status_code=403, detail="Dispositivo no aprobado.")
    if not await user_has_module_access(auth, "checklist_tareas"):
        raise HTTPException(status_code=403, detail="Sin acceso a CheckList Tareas.")
    role = str(auth.get("role") or "").strip().lower()
    auth["role"] = role
    if role == "admin":
        auth["checklist_profile"] = "ADMIN_GLOBAL"
    else:
        async with auth_db() as db:
            access = await _fetch_one(
                db,
                """
                SELECT profile, scope, sector, metadata_json
                FROM auth_user_app_access
                WHERE username = ? AND module = 'checklist_tareas' AND enabled = 1
                """,
                (auth["username"],),
            )
        auth["checklist_profile"] = str((access or {}).get("profile") or "OPERADOR").strip().upper()
    return auth


def _can_manage(auth: dict[str, Any]) -> bool:
    return (
        str(auth.get("role") or "").strip().lower() == "admin"
        or str(auth.get("checklist_profile") or "").strip().upper() == "ADMIN_SECTOR"
    )


async def _require_admin(request: Request) -> dict[str, Any]:
    auth = await _require_user(request)
    if not _can_manage(auth):
        raise HTTPException(status_code=403, detail="Requiere ADMIN_SECTOR o administrador global.")
    return auth


async def _fetch_one(
    db: aiosqlite.Connection, sql: str, args: tuple[Any, ...] = ()
) -> dict[str, Any] | None:
    async with db.execute(sql, args) as cur:
        row = await cur.fetchone()
    return dict(row) if row else None


async def _fetch_all(
    db: aiosqlite.Connection, sql: str, args: tuple[Any, ...] = ()
) -> list[dict[str, Any]]:
    async with db.execute(sql, args) as cur:
        return [dict(row) for row in await cur.fetchall()]


async def _operator_shift_map() -> dict[str, str | None]:
    async with auth_db() as db:
        rows = await _fetch_all(
            db,
            """
            SELECT username, metadata_json
            FROM auth_user_app_access
            WHERE module = 'checklist_tareas' AND enabled = 1
            """,
        )
    result: dict[str, str | None] = {}
    for row in rows:
        try:
            metadata = json.loads(row.get("metadata_json") or "{}")
        except json.JSONDecodeError:
            metadata = {}
        shift = metadata.get("shift")
        result[row["username"]] = shift if shift in {"Mañana", "Tarde", "Noche"} else None
    return result


async def _sector(db: aiosqlite.Connection, code: str = "MAPA_ALMACEN") -> dict[str, Any]:
    row = await _fetch_one(db, "SELECT * FROM checklist_sector WHERE code = ? AND active = 1", (code,))
    if not row:
        raise HTTPException(status_code=404, detail="Sector no encontrado.")
    return row


async def _audit(
    db: aiosqlite.Connection,
    *,
    sector_id: int | None,
    actor: str,
    action: str,
    entity_type: str,
    entity_id: str | int,
    before: Any = None,
    after: Any = None,
) -> None:
    await db.execute(
        """
        INSERT INTO checklist_audit
            (sector_id, actor_username, action, entity_type, entity_id, before_json, after_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            sector_id,
            actor,
            action,
            entity_type,
            str(entity_id),
            json.dumps(before, ensure_ascii=False, default=str) if before is not None else None,
            json.dumps(after, ensure_ascii=False, default=str) if after is not None else None,
            now_iso(),
        ),
    )


def _is_due(schedule: dict[str, Any], target: date) -> bool:
    if schedule.get("starts_on") and target.isoformat() < schedule["starts_on"]:
        return False
    kind = schedule.get("schedule_type")
    if kind == "weekly":
        try:
            weekdays = json.loads(schedule.get("weekdays_json") or "[]")
        except json.JSONDecodeError:
            weekdays = []
        return target.weekday() in {int(item) for item in weekdays}
    if kind == "specific_date":
        return schedule.get("specific_date") == target.isoformat()
    if kind == "monthly_day":
        return int(schedule.get("monthly_day") or 0) == target.day
    return False


def _derived_status(row: dict[str, Any], today: str) -> str:
    status = row.get("stored_status") or "pending"
    if status != "pending":
        return status
    effective = row.get("effective_date") or row["scheduled_date"]
    if effective < today and not row.get("allow_delay"):
        return "overdue"
    return "pending"


async def _assignment_rows(db: aiosqlite.Connection, sector_id: int) -> list[dict[str, Any]]:
    return await _fetch_all(
        db,
        """
        SELECT a.*, t.code task_code, t.title task_title, t.description task_description,
               t.duration_minutes task_duration_minutes,
               s.schedule_type, s.weekdays_json, s.specific_date, s.monthly_day
        FROM checklist_assignment a
        JOIN checklist_task t ON t.task_id = a.task_id
        LEFT JOIN checklist_schedule s ON s.assignment_id = a.assignment_id
        WHERE a.sector_id = ? AND a.active = 1 AND t.active = 1 AND s.schedule_id IS NOT NULL
        ORDER BY t.title, a.assignment_id
        """,
        (sector_id,),
    )


async def _delegations_for_date(
    db: aiosqlite.Connection, sector_id: int, target: str
) -> tuple[dict[int, str], dict[str, str]]:
    rows = await _fetch_all(
        db,
        """
        SELECT d.delegation_id, d.from_username, d.to_username, da.assignment_id
        FROM checklist_delegation d
        LEFT JOIN checklist_delegation_assignment da ON da.delegation_id = d.delegation_id
        WHERE d.sector_id = ? AND d.active = 1 AND d.date_from <= ? AND d.date_to >= ?
        ORDER BY d.delegation_id DESC
        """,
        (sector_id, target, target),
    )
    by_assignment: dict[int, str] = {}
    legacy_by_user: dict[str, str] = {}
    for row in rows:
        if row.get("assignment_id") is None:
            legacy_by_user.setdefault(row["from_username"], row["to_username"])
        else:
            by_assignment.setdefault(int(row["assignment_id"]), row["to_username"])
    return by_assignment, legacy_by_user


def _delegated_to(
    assignment: dict[str, Any],
    by_assignment: dict[int, str],
    legacy_by_user: dict[str, str],
) -> str | None:
    return by_assignment.get(int(assignment["assignment_id"])) or legacy_by_user.get(assignment["username"])


def _board_item(
    assignment: dict[str, Any],
    scheduled_date: str,
    occurrence: dict[str, Any] | None,
    delegated_to: str | None,
    shift_map: dict[str, str | None],
    today: str,
) -> dict[str, Any]:
    occurrence = occurrence or {}
    row = {
        "occurrence_id": occurrence.get("occurrence_id"),
        "assignment_id": assignment["assignment_id"],
        "task_id": assignment["task_id"],
        "task_code": assignment["task_code"],
        "title": assignment.get("instructions_override") or assignment["task_title"],
        "canonical_title": assignment["task_title"],
        "scheduled_date": scheduled_date,
        "effective_date": occurrence.get("effective_date") or scheduled_date,
        "stored_status": occurrence.get("status") or "pending",
        "note": occurrence.get("note") or "",
        "completed_by": occurrence.get("completed_by"),
        "completed_at": occurrence.get("completed_at"),
        "updated_by": occurrence.get("updated_by"),
        "updated_at": occurrence.get("updated_at"),
        "version": occurrence.get("version", 0),
        "assigned_username": assignment["username"],
        "responsible_username": delegated_to or assignment["username"],
        "delegated": bool(delegated_to),
        "shift": shift_map.get(delegated_to or assignment["username"]),
        "duration_minutes": assignment.get("task_duration_minutes"),
        "allow_delay": bool(assignment.get("allow_delay")),
        "eventual": False,
    }
    row["status"] = _derived_status(row, today)
    row["coverage"] = [
        {
            "assignment_id": row["assignment_id"],
            "scheduled_date": row["scheduled_date"],
            "version": row["version"],
            "status": row["status"],
        }
    ]
    row["coverage_count"] = 1
    return row


def _consolidate_delegated_items(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    standalone: list[dict[str, Any]] = []
    for row in rows:
        if row.get("eventual") or row.get("task_id") is None:
            standalone.append(row)
            continue
        key = (
            row["task_id"],
            row.get("responsible_username"),
            row.get("effective_date"),
        )
        grouped.setdefault(key, []).append(row)

    result = list(standalone)
    for members in grouped.values():
        if len(members) == 1 or not any(row.get("delegated") for row in members):
            result.extend(members)
            continue
        primary = next((row for row in members if not row.get("delegated")), members[0]).copy()
        coverage = [ref for row in members for ref in row.get("coverage", [])]
        completed = next((row for row in members if row.get("status") == "completed"), None)
        if completed:
            primary["status"] = "completed"
            primary["stored_status"] = "completed"
            for field in ("completed_by", "completed_at", "updated_by", "updated_at"):
                primary[field] = completed.get(field)
        elif all(row.get("status") == "not_applicable" for row in members):
            primary["status"] = "not_applicable"
            primary["stored_status"] = "not_applicable"
        elif any(row.get("status") == "overdue" for row in members):
            primary["status"] = "overdue"
            primary["stored_status"] = "pending"
        else:
            primary["status"] = "pending"
            primary["stored_status"] = "pending"
        primary["coverage"] = coverage
        primary["coverage_count"] = len(coverage)
        primary["assigned_usernames"] = sorted({row["assigned_username"] for row in members})
        primary["delegated_from_usernames"] = sorted(
            {row["assigned_username"] for row in members if row.get("delegated")}
        )
        primary["delegated"] = bool(primary["delegated_from_usernames"])
        result.append(primary)
    return result


@router.get("/context")
async def context(request: Request):
    auth = await _require_user(request)
    async with checklist_db() as db:
        sectors = await _fetch_all(db, "SELECT sector_id, code, name FROM checklist_sector WHERE active = 1 ORDER BY name")
    async with auth_db() as adb:
        users = await _fetch_all(
            adb,
            """
            SELECT u.username, u.display_name, u.role,
                   COALESCE(a.profile, CASE WHEN u.role = 'admin' THEN 'ADMIN' ELSE '' END) profile,
                   a.metadata_json
            FROM auth_users u
            LEFT JOIN auth_user_app_access a
              ON a.username = u.username AND a.module = 'checklist_tareas' AND a.enabled = 1
            WHERE u.active = 1 AND (a.access_id IS NOT NULL OR u.role = 'admin')
            ORDER BY u.display_name, u.username
            """,
        )
    for user in users:
        try:
            metadata = json.loads(user.pop("metadata_json") or "{}")
        except json.JSONDecodeError:
            metadata = {}
        user["shift"] = metadata.get("shift")
    return {
        "user": {"username": auth["username"], "display_name": auth.get("display_name"), "role": auth.get("role")},
        "is_admin": _can_manage(auth),
        "permissions": {"manage_catalog": _can_manage(auth)},
        "checklist_profile": auth.get("checklist_profile"),
        "sectors": sectors,
        "users": users,
        "statuses": ["pending", "overdue", "completed", "not_applicable"],
    }


@router.get("/board")
async def board(
    request: Request,
    target_date: str = Query(alias="date"),
    sector: str = "MAPA_ALMACEN",
    overdue_days: int = Query(default=30, ge=0, le=180),
):
    await _require_user(request)
    target_iso = _iso_date(target_date)
    target = date.fromisoformat(target_iso)
    today = date.today().isoformat()
    shift_map = await _operator_shift_map()
    async with checklist_db() as db:
        sector_row = await _sector(db, sector)
        sector_id = int(sector_row["sector_id"])
        assignments = await _assignment_rows(db, sector_id)
        date_from = min(target, date.today() - timedelta(days=overdue_days)).isoformat()
        date_to = max(target, date.today()).isoformat()
        occurrences = await _fetch_all(
            db,
            """
            SELECT * FROM checklist_occurrence
            WHERE sector_id = ? AND (scheduled_date BETWEEN ? AND ? OR effective_date BETWEEN ? AND ?)
            """,
            (sector_id, date_from, date_to, date_from, date_to),
        )
        by_key = {(row["assignment_id"], row["scheduled_date"]): row for row in occurrences if row["assignment_id"] is not None}
        target_assignment_delegations, target_legacy_delegations = await _delegations_for_date(
            db, sector_id, target_iso
        )

        items: list[dict[str, Any]] = []
        for assignment in assignments:
            occurrence = by_key.get((assignment["assignment_id"], target_iso))
            if _is_due(assignment, target):
                if not occurrence or occurrence["effective_date"] == target_iso:
                    items.append(
                        _board_item(
                            assignment,
                            target_iso,
                            occurrence,
                            _delegated_to(assignment, target_assignment_delegations, target_legacy_delegations),
                            shift_map,
                            today,
                        )
                    )
            for moved in occurrences:
                if (
                    moved["assignment_id"] == assignment["assignment_id"]
                    and moved["scheduled_date"] != target_iso
                    and moved["effective_date"] == target_iso
                ):
                    items.append(
                        _board_item(
                            assignment,
                            moved["scheduled_date"],
                            moved,
                            _delegated_to(assignment, target_assignment_delegations, target_legacy_delegations),
                            shift_map,
                            today,
                        )
                    )

        for occurrence in occurrences:
            if occurrence["assignment_id"] is None and occurrence["effective_date"] == target_iso:
                eventual = dict(occurrence)
                eventual.update(
                    {
                        "task_id": None,
                        "task_code": "EVENTUAL",
                        "title": occurrence["eventual_title"],
                        "canonical_title": occurrence["eventual_title"],
                        "stored_status": occurrence["status"],
                        "assigned_username": occurrence["responsible_username"],
                        "responsible_username": target_legacy_delegations.get(occurrence["responsible_username"], occurrence["responsible_username"]),
                        "delegated": occurrence["responsible_username"] in target_legacy_delegations,
                        "shift": shift_map.get(target_legacy_delegations.get(occurrence["responsible_username"], occurrence["responsible_username"])),
                        "eventual": True,
                        "allow_delay": bool(occurrence["allow_delay"]),
                    }
                )
                eventual["status"] = _derived_status(eventual, today)
                items.append(eventual)

        items = _consolidate_delegated_items(items)
        overdue_candidates: list[dict[str, Any]] = []
        if overdue_days:
            start = date.today() - timedelta(days=overdue_days)
            for day_offset in range(overdue_days):
                due_date = start + timedelta(days=day_offset)
                due_iso = due_date.isoformat()
                assignment_delegations, legacy_delegations = await _delegations_for_date(
                    db, sector_id, due_iso
                )
                for assignment in assignments:
                    if not _is_due(assignment, due_date):
                        continue
                    occurrence = by_key.get((assignment["assignment_id"], due_iso))
                    if occurrence and occurrence["effective_date"] != due_iso:
                        continue
                    item = _board_item(
                        assignment,
                        due_iso,
                        occurrence,
                        _delegated_to(assignment, assignment_delegations, legacy_delegations),
                        shift_map,
                        today,
                    )
                    overdue_candidates.append(item)

        overdue = [
            item for item in _consolidate_delegated_items(overdue_candidates)
            if item["status"] == "overdue"
        ]

    items.sort(key=lambda row: (row["status"] == "completed", row.get("responsible_username") or "", row["title"]))
    overdue.sort(key=lambda row: (row["scheduled_date"], row["title"]))
    return {
        "sector": sector_row,
        "date": target_iso,
        "items": items,
        "overdue": overdue,
        "summary": {
            "total": len([row for row in items if row["status"] != "not_applicable"]),
            "completed": len([row for row in items if row["status"] == "completed"]),
            "pending": len([row for row in items if row["status"] == "pending"]),
            "overdue": len(overdue),
            "minutes_pending": sum(int(row.get("duration_minutes") or 0) for row in items if row["status"] in {"pending", "overdue"}),
        },
    }


async def _assignment(db: aiosqlite.Connection, assignment_id: int) -> dict[str, Any]:
    row = await _fetch_one(
        db,
        """
        SELECT a.*, t.title task_title, t.duration_minutes task_duration_minutes,
               s.schedule_type, s.weekdays_json, s.specific_date, s.monthly_day
        FROM checklist_assignment a
        JOIN checklist_task t ON t.task_id = a.task_id
        LEFT JOIN checklist_schedule s ON s.assignment_id = a.assignment_id
        WHERE a.assignment_id = ?
        """,
        (assignment_id,),
    )
    if not row:
        raise HTTPException(status_code=404, detail="Asignacion no encontrada.")
    return row


async def _apply_occurrence_action(
    db: aiosqlite.Connection,
    assignment: dict[str, Any],
    scheduled: str,
    req: OccurrenceActionRequest | GroupOccurrenceActionRequest,
    auth: dict[str, Any],
    version: int | None = None,
) -> dict[str, Any]:
        assignment_id = int(assignment["assignment_id"])
        before = await _fetch_one(
            db,
            "SELECT * FROM checklist_occurrence WHERE assignment_id = ? AND scheduled_date = ?",
            (assignment_id, scheduled),
        )
        if not before and not _is_due(assignment, date.fromisoformat(scheduled)):
            raise HTTPException(status_code=400, detail="La asignacion no corresponde a la fecha indicada.")
        expected_version = version if version is not None else getattr(req, "version", None)
        if expected_version is not None and before and int(before["version"]) != expected_version:
            raise HTTPException(status_code=409, detail="La tarea fue modificada por otro usuario. Actualiza el tablero.")
        effective = before["effective_date"] if before else scheduled
        status = before["status"] if before else "pending"
        completed_by = before.get("completed_by") if before else None
        completed_at = before.get("completed_at") if before else None
        if req.action == "complete":
            status, completed_by, completed_at = "completed", auth["username"], now_iso()
        elif req.action == "not_applicable":
            status, completed_by, completed_at = "not_applicable", None, None
        elif req.action == "pending":
            status, completed_by, completed_at = "pending", None, None
        elif req.action == "reprogram":
            if not req.effective_date:
                raise HTTPException(status_code=400, detail="La reprogramacion requiere una fecha.")
            effective = _iso_date(req.effective_date, "Nueva fecha")
            status, completed_by, completed_at = "pending", None, None
        timestamp = now_iso()
        await db.execute(
            """
            INSERT INTO checklist_occurrence
                (assignment_id, sector_id, scheduled_date, effective_date, status, note,
                 completed_by, completed_at, updated_by, updated_at, version, allow_delay)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
            ON CONFLICT(assignment_id, scheduled_date) DO UPDATE SET
                effective_date=excluded.effective_date, status=excluded.status, note=excluded.note,
                completed_by=excluded.completed_by, completed_at=excluded.completed_at,
                updated_by=excluded.updated_by, updated_at=excluded.updated_at,
                version=checklist_occurrence.version + 1
            """,
            (
                assignment_id, assignment["sector_id"], scheduled, effective, status,
                _clean(req.note), completed_by, completed_at, auth["username"], timestamp,
                int(assignment["allow_delay"]),
            ),
        )
        after = await _fetch_one(
            db,
            "SELECT * FROM checklist_occurrence WHERE assignment_id = ? AND scheduled_date = ?",
            (assignment_id, scheduled),
        )
        await _audit(
            db,
            sector_id=assignment["sector_id"], actor=auth["username"], action=req.action,
            entity_type="occurrence", entity_id=f"{assignment_id}:{scheduled}", before=before, after=after,
        )
        return after


@router.put("/occurrences/assignment/{assignment_id}/{scheduled_date}")
async def update_occurrence(
    assignment_id: int,
    scheduled_date: str,
    req: OccurrenceActionRequest,
    request: Request,
):
    auth = await _require_user(request)
    scheduled = _iso_date(scheduled_date, "Fecha programada")
    async with checklist_db() as db:
        assignment = await _assignment(db, assignment_id)
        after = await _apply_occurrence_action(db, assignment, scheduled, req, auth)
        await db.commit()
    return {"ok": True, "occurrence": after}


@router.put("/occurrences/group")
async def update_occurrence_group(
    req: GroupOccurrenceActionRequest,
    request: Request,
):
    auth = await _require_user(request)
    refs: list[tuple[OccurrenceReference, str, dict[str, Any], dict[str, Any] | None]] = []
    seen: set[tuple[int, str]] = set()
    async with checklist_db() as db:
        for ref in req.items:
            scheduled = _iso_date(ref.scheduled_date, "Fecha programada")
            key = (ref.assignment_id, scheduled)
            if key in seen:
                continue
            seen.add(key)
            assignment = await _assignment(db, ref.assignment_id)
            before = await _fetch_one(
                db,
                "SELECT * FROM checklist_occurrence WHERE assignment_id=? AND scheduled_date=?",
                key,
            )
            if not before and not _is_due(assignment, date.fromisoformat(scheduled)):
                raise HTTPException(status_code=400, detail="Una asignacion no corresponde a la fecha indicada.")
            if ref.version is not None and before and int(before["version"]) != ref.version:
                raise HTTPException(status_code=409, detail="Una tarea fue modificada por otro usuario. Actualiza el tablero.")
            refs.append((ref, scheduled, assignment, before))

        if len({int(item[2]["task_id"]) for item in refs}) != 1:
            raise HTTPException(status_code=400, detail="Las tareas consolidadas deben compartir el mismo maestro.")
        display_dates = {item[3]["effective_date"] if item[3] else item[1] for item in refs}
        if len(display_dates) != 1:
            raise HTTPException(status_code=400, detail="Las tareas consolidadas deben corresponder a la misma fecha efectiva.")
        display_date = next(iter(display_dates))
        sector_ids = {int(item[2]["sector_id"]) for item in refs}
        if len(sector_ids) != 1:
            raise HTTPException(status_code=400, detail="Las tareas consolidadas deben pertenecer al mismo sector.")
        assignment_delegations, legacy_delegations = await _delegations_for_date(
            db, next(iter(sector_ids)), display_date
        )
        responsibles = {
            _delegated_to(item[2], assignment_delegations, legacy_delegations) or item[2]["username"]
            for item in refs
        }
        if len(responsibles) != 1:
            raise HTTPException(status_code=400, detail="Las tareas ya no corresponden al mismo responsable.")

        updated = []
        for ref, scheduled, assignment, _before in refs:
            updated.append(
                await _apply_occurrence_action(
                    db, assignment, scheduled, req, auth, version=ref.version
                )
            )
        await db.commit()
    return {"ok": True, "occurrences": updated}


@router.post("/occurrences/eventual")
async def create_eventual(req: EventualRequest, request: Request):
    auth = await _require_user(request)
    title = _clean(req.title)
    username = _clean(req.username).lower()
    if not title or not username:
        raise HTTPException(status_code=400, detail="Tarea y responsable son obligatorios.")
    target = _iso_date(req.date)
    async with auth_db() as adb:
        user = await _fetch_one(adb, "SELECT username FROM auth_users WHERE username = ? AND active = 1", (username,))
    if not user:
        raise HTTPException(status_code=400, detail="Responsable inexistente o inactivo.")
    shift_map = await _operator_shift_map()
    async with checklist_db() as db:
        sector = await _sector(db)
        timestamp = now_iso()
        cur = await db.execute(
            """
            INSERT INTO checklist_occurrence
                (assignment_id, sector_id, scheduled_date, effective_date, status, updated_by, updated_at,
                 eventual_title, responsible_username, shift, duration_minutes, allow_delay)
            VALUES (NULL, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                sector["sector_id"], target, target, auth["username"], timestamp, title, username,
                shift_map.get(username), req.duration_minutes, int(req.allow_delay),
            ),
        )
        occurrence_id = int(cur.lastrowid)
        after = await _fetch_one(db, "SELECT * FROM checklist_occurrence WHERE occurrence_id = ?", (occurrence_id,))
        await _audit(
            db, sector_id=sector["sector_id"], actor=auth["username"], action="create_eventual",
            entity_type="occurrence", entity_id=occurrence_id, after=after,
        )
        await db.commit()
    return {"ok": True, "occurrence": after}


@router.delete("/occurrences/eventual/{occurrence_id}")
async def delete_eventual(occurrence_id: int, request: Request):
    auth = await _require_user(request)
    async with checklist_db() as db:
        before = await _fetch_one(
            db, "SELECT * FROM checklist_occurrence WHERE occurrence_id = ? AND assignment_id IS NULL", (occurrence_id,)
        )
        if not before:
            raise HTTPException(status_code=404, detail="Tarea eventual no encontrada.")
        await db.execute("DELETE FROM checklist_occurrence WHERE occurrence_id = ?", (occurrence_id,))
        await _audit(
            db, sector_id=before["sector_id"], actor=auth["username"], action="delete_eventual",
            entity_type="occurrence", entity_id=occurrence_id, before=before,
        )
        await db.commit()
    return {"ok": True}


@router.put("/occurrences/eventual/{occurrence_id}")
async def update_eventual(
    occurrence_id: int, req: OccurrenceActionRequest, request: Request
):
    auth = await _require_user(request)
    async with checklist_db() as db:
        before = await _fetch_one(
            db,
            "SELECT * FROM checklist_occurrence WHERE occurrence_id = ? AND assignment_id IS NULL",
            (occurrence_id,),
        )
        if not before:
            raise HTTPException(status_code=404, detail="Tarea eventual no encontrada.")
        if req.version is not None and int(before["version"]) != req.version:
            raise HTTPException(status_code=409, detail="La tarea fue modificada por otro usuario. Actualiza el tablero.")
        status = before["status"]
        effective = before["effective_date"]
        completed_by = before.get("completed_by")
        completed_at = before.get("completed_at")
        if req.action == "complete":
            status, completed_by, completed_at = "completed", auth["username"], now_iso()
        elif req.action == "not_applicable":
            status, completed_by, completed_at = "not_applicable", None, None
        elif req.action == "pending":
            status, completed_by, completed_at = "pending", None, None
        elif req.action == "reprogram":
            if not req.effective_date:
                raise HTTPException(status_code=400, detail="La reprogramacion requiere una fecha.")
            effective = _iso_date(req.effective_date, "Nueva fecha")
            status, completed_by, completed_at = "pending", None, None
        await db.execute(
            """
            UPDATE checklist_occurrence SET
                effective_date=?, status=?, note=?, completed_by=?, completed_at=?,
                updated_by=?, updated_at=?, version=version + 1
            WHERE occurrence_id=?
            """,
            (
                effective, status, _clean(req.note), completed_by, completed_at,
                auth["username"], now_iso(), occurrence_id,
            ),
        )
        after = await _fetch_one(db, "SELECT * FROM checklist_occurrence WHERE occurrence_id = ?", (occurrence_id,))
        await _audit(
            db, sector_id=before["sector_id"], actor=auth["username"], action=req.action,
            entity_type="occurrence", entity_id=occurrence_id, before=before, after=after,
        )
        await db.commit()
    return {"ok": True, "occurrence": after}


@router.get("/catalog")
async def catalog(request: Request):
    await _require_admin(request)
    shift_map = await _operator_shift_map()
    async with checklist_db() as db:
        sector = await _sector(db)
        tasks = await _fetch_all(
            db,
            """
            SELECT t.*,
                   SUM(CASE WHEN a.active = 1 THEN 1 ELSE 0 END) assignment_count,
                   COUNT(a.assignment_id) assignment_count_total
            FROM checklist_task t
            LEFT JOIN checklist_assignment a ON a.task_id = t.task_id
            GROUP BY t.task_id ORDER BY t.title
            """,
        )
        assignments = await _fetch_all(
            db,
            """
            SELECT a.*, t.title task_title, t.duration_minutes task_duration_minutes,
                   s.schedule_type, s.weekdays_json, s.specific_date, s.monthly_day
            FROM checklist_assignment a
            JOIN checklist_task t ON t.task_id = a.task_id
            LEFT JOIN checklist_schedule s ON s.assignment_id = a.assignment_id
            WHERE a.sector_id = ? ORDER BY t.title, a.username, a.assignment_id
            """,
            (sector["sector_id"],),
        )
    for item in assignments:
        item["weekdays"] = json.loads(item.pop("weekdays_json") or "[]")
        item["shift"] = shift_map.get(item["username"])
        item["duration_minutes"] = item["task_duration_minutes"]
    return {"sector": sector, "tasks": tasks, "assignments": assignments}


def _export_schedule_text(item: dict[str, Any]) -> str:
    kind = item.get("schedule_type")
    if kind == "weekly":
        try:
            days = json.loads(item.get("weekdays_json") or "[]")
        except json.JSONDecodeError:
            days = []
        labels = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
        return ", ".join(labels[int(day)] for day in days if 0 <= int(day) < len(labels))
    if kind == "specific_date":
        return item.get("specific_date") or ""
    if kind == "monthly_day":
        return f"Día {item.get('monthly_day')}"
    return "Sin frecuencia"


@router.get("/catalog/export.xlsx")
async def export_catalog_xlsx(request: Request):
    await _require_admin(request)
    shift_map = await _operator_shift_map()
    async with checklist_db() as db:
        sector = await _sector(db)
        tasks = await _fetch_all(
            db,
            """
            SELECT t.*, SUM(CASE WHEN a.active=1 THEN 1 ELSE 0 END) assignment_count,
                   COUNT(a.assignment_id) assignment_count_total
            FROM checklist_task t
            LEFT JOIN checklist_assignment a ON a.task_id=t.task_id
            GROUP BY t.task_id ORDER BY t.title
            """,
        )
        assignments = await _fetch_all(
            db,
            """
            SELECT a.*, t.code task_code, t.title task_title,
                   t.duration_minutes task_duration_minutes,
                   s.schedule_type, s.weekdays_json, s.specific_date, s.monthly_day
            FROM checklist_assignment a
            JOIN checklist_task t ON t.task_id=a.task_id
            LEFT JOIN checklist_schedule s ON s.assignment_id=a.assignment_id
            WHERE a.sector_id=?
            ORDER BY t.title, a.username, a.assignment_id
            """,
            (sector["sector_id"],),
        )

    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output, {"in_memory": True})
    workbook.set_properties(
        {
            "title": "CheckList Tareas - Catálogo y asignaciones",
            "subject": f"Sector {sector['name']}",
            "company": "Coto C.I.C.S.A.",
            "comments": "Exportado desde VigIA",
        }
    )
    title_format = workbook.add_format(
        {"bold": True, "font_color": "#FFFFFF", "bg_color": "#0E1620", "font_size": 14}
    )
    note_format = workbook.add_format({"font_color": "#5C6773", "italic": True})
    header_format = workbook.add_format(
        {"bold": True, "font_color": "#FFFFFF", "bg_color": "#1F7A4D", "border": 0}
    )
    inactive_format = workbook.add_format({"font_color": "#8A3038", "bg_color": "#F7D7DA"})
    wrap_format = workbook.add_format({"text_wrap": True, "valign": "top"})

    task_sheet = workbook.add_worksheet("Tareas")
    task_sheet.hide_gridlines(2)
    task_sheet.freeze_panes(3, 0)
    task_sheet.merge_range("A1:G1", "Maestro de tareas", title_format)
    task_sheet.merge_range("A2:G2", f"Sector: {sector['name']} · Exportado: {datetime.now().strftime('%d/%m/%Y %H:%M')}", note_format)
    task_headers = [
        "Código", "Tarea", "Descripción", "Minutos", "Estado",
        "Asignaciones activas", "Asignaciones totales",
    ]
    task_rows = [
        [
            row["code"], row["title"], row.get("description") or "",
            row.get("duration_minutes"), "Activa" if row["active"] else "Inactiva",
            int(row.get("assignment_count") or 0), int(row.get("assignment_count_total") or 0),
        ]
        for row in tasks
    ]
    task_sheet.write_row(2, 0, task_headers, header_format)
    for row_index, values in enumerate(task_rows, 3):
        task_sheet.write_row(row_index, 0, values)
        wrapped_lines = max(
            1,
            (len(str(values[1])) + 54) // 55,
            (len(str(values[2])) + 47) // 48,
        )
        task_sheet.set_row(row_index, min(105, max(24, wrapped_lines * 16)))
    task_sheet.add_table(2, 0, 2 + len(task_rows), len(task_headers) - 1, {
        "name": "TablaTareas",
        "style": "Table Style Medium 4",
        "columns": [{"header": header} for header in task_headers],
    })
    task_sheet.set_column("A:A", 14)
    task_sheet.set_column("B:B", 55, wrap_format)
    task_sheet.set_column("C:C", 48, wrap_format)
    task_sheet.set_column("D:D", 11)
    task_sheet.set_column("E:E", 12)
    task_sheet.set_column("F:G", 20)
    task_sheet.conditional_format(3, 4, 2 + len(task_rows), 4, {
        "type": "text", "criteria": "containing", "value": "Inactiva", "format": inactive_format,
    })

    assignment_sheet = workbook.add_worksheet("Asignaciones")
    assignment_sheet.hide_gridlines(2)
    assignment_sheet.freeze_panes(3, 0)
    assignment_sheet.merge_range("A1:J1", "Asignaciones de tareas", title_format)
    assignment_sheet.merge_range("A2:J2", f"Sector: {sector['name']} · Incluye activas e inactivas", note_format)
    assignment_headers = [
        "ID asignación", "Código", "Tarea maestra", "Detalle particular", "Usuario",
        "Turno", "Minutos heredados", "Frecuencia", "Permite atraso", "Estado",
    ]
    assignment_rows = [
        [
            int(row["assignment_id"]), row["task_code"], row["task_title"],
            row.get("instructions_override") or "", row["username"],
            shift_map.get(row["username"]) or "Sin turno", row.get("task_duration_minutes"),
            _export_schedule_text(row), "Sí" if row.get("allow_delay") else "No",
            "Activa" if row["active"] else "Inactiva",
        ]
        for row in assignments
    ]
    assignment_sheet.write_row(2, 0, assignment_headers, header_format)
    for row_index, values in enumerate(assignment_rows, 3):
        assignment_sheet.write_row(row_index, 0, values)
        wrapped_lines = max(
            1,
            (len(str(values[2])) + 49) // 50,
            (len(str(values[3])) + 41) // 42,
        )
        assignment_sheet.set_row(row_index, min(105, max(24, wrapped_lines * 16)))
    assignment_sheet.add_table(2, 0, 2 + len(assignment_rows), len(assignment_headers) - 1, {
        "name": "TablaAsignaciones",
        "style": "Table Style Medium 4",
        "columns": [{"header": header} for header in assignment_headers],
    })
    assignment_sheet.set_column("A:B", 15)
    assignment_sheet.set_column("C:C", 52, wrap_format)
    assignment_sheet.set_column("D:D", 45, wrap_format)
    assignment_sheet.set_column("E:F", 16)
    assignment_sheet.set_column("G:G", 19)
    assignment_sheet.set_column("H:H", 42)
    assignment_sheet.set_column("I:J", 15)
    assignment_sheet.conditional_format(3, 9, 2 + len(assignment_rows), 9, {
        "type": "text", "criteria": "containing", "value": "Inactiva", "format": inactive_format,
    })
    workbook.close()
    output.seek(0)
    filename = f"checklist_tareas_{date.today().strftime('%Y%m%d')}.xlsx"
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/admin/tasks")
async def create_task(req: TaskRequest, request: Request):
    auth = await _require_admin(request)
    title = _clean(req.title)
    if not title:
        raise HTTPException(status_code=400, detail="El nombre de la tarea es obligatorio.")
    async with checklist_db() as db:
        sector = await _sector(db)
        async with db.execute("SELECT COALESCE(MAX(task_id), 0) + 1 FROM checklist_task") as cur:
            next_id = int((await cur.fetchone())[0])
        code = f"USR-{next_id:05d}"
        cur = await db.execute(
            "INSERT INTO checklist_task (code, title, description, duration_minutes, active, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (code, title, _clean(req.description), req.duration_minutes, int(req.active), now_iso()),
        )
        task_id = int(cur.lastrowid)
        after = await _fetch_one(db, "SELECT * FROM checklist_task WHERE task_id = ?", (task_id,))
        await _audit(db, sector_id=sector["sector_id"], actor=auth["username"], action="create", entity_type="task", entity_id=task_id, after=after)
        await db.commit()
    return {"ok": True, "task": after}


@router.put("/admin/tasks/{task_id}")
async def update_task(task_id: int, req: TaskRequest, request: Request):
    auth = await _require_admin(request)
    title = _clean(req.title)
    if not title:
        raise HTTPException(status_code=400, detail="El nombre de la tarea es obligatorio.")
    async with checklist_db() as db:
        sector = await _sector(db)
        before = await _fetch_one(db, "SELECT * FROM checklist_task WHERE task_id = ?", (task_id,))
        if not before:
            raise HTTPException(status_code=404, detail="Tarea no encontrada.")
        timestamp = now_iso()
        assignments_deactivated: list[dict[str, Any]] = []
        if bool(before["active"]) and not req.active:
            assignments_deactivated = await _fetch_all(
                db,
                "SELECT assignment_id, username, active FROM checklist_assignment WHERE task_id=? AND active=1",
                (task_id,),
            )
            await db.execute(
                "UPDATE checklist_assignment SET active=0, updated_at=? WHERE task_id=? AND active=1",
                (timestamp, task_id),
            )
        await db.execute(
            "UPDATE checklist_task SET title=?, description=?, duration_minutes=?, active=?, updated_at=? WHERE task_id=?",
            (title, _clean(req.description), req.duration_minutes, int(req.active), timestamp, task_id),
        )
        after = await _fetch_one(db, "SELECT * FROM checklist_task WHERE task_id = ?", (task_id,))
        await _audit(db, sector_id=sector["sector_id"], actor=auth["username"], action="update", entity_type="task", entity_id=task_id, before=before, after=after)
        if assignments_deactivated:
            await _audit(
                db,
                sector_id=sector["sector_id"],
                actor=auth["username"],
                action="deactivate_by_task",
                entity_type="assignment_batch",
                entity_id=task_id,
                before=assignments_deactivated,
                after={
                    "task_id": task_id,
                    "active": 0,
                    "assignment_ids": [row["assignment_id"] for row in assignments_deactivated],
                },
            )
        await db.commit()
    return {
        "ok": True,
        "task": after,
        "assignments_deactivated": len(assignments_deactivated),
    }


async def _write_schedule(db: aiosqlite.Connection, assignment_id: int, schedule: ScheduleRequest) -> None:
    if schedule.type is None:
        await db.execute("DELETE FROM checklist_schedule WHERE assignment_id = ?", (assignment_id,))
        return
    weekdays = sorted({int(day) for day in schedule.weekdays if 0 <= int(day) <= 6})
    specific_date = _iso_date(schedule.date, "Fecha especifica") if schedule.type == "specific_date" and schedule.date else None
    if schedule.type == "weekly" and not weekdays:
        raise HTTPException(status_code=400, detail="La frecuencia semanal requiere al menos un dia.")
    if schedule.type == "specific_date" and not specific_date:
        raise HTTPException(status_code=400, detail="Falta la fecha especifica.")
    if schedule.type == "monthly_day" and not schedule.day:
        raise HTTPException(status_code=400, detail="Falta el dia mensual.")
    await db.execute(
        """
        INSERT INTO checklist_schedule
            (assignment_id, schedule_type, weekdays_json, specific_date, monthly_day, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(assignment_id) DO UPDATE SET
            schedule_type=excluded.schedule_type, weekdays_json=excluded.weekdays_json,
            specific_date=excluded.specific_date, monthly_day=excluded.monthly_day,
            updated_at=excluded.updated_at
        """,
        (assignment_id, schedule.type, json.dumps(weekdays), specific_date, schedule.day, now_iso()),
    )


async def _validate_active_user(username: str) -> str:
    value = _clean(username).lower()
    async with auth_db() as db:
        row = await _fetch_one(db, "SELECT username FROM auth_users WHERE username = ? AND active = 1", (value,))
    if not row:
        raise HTTPException(status_code=400, detail="Usuario inexistente o inactivo.")
    return value


@router.post("/admin/assignments")
async def create_assignment(req: AssignmentRequest, request: Request):
    auth = await _require_admin(request)
    username = await _validate_active_user(req.username)
    async with checklist_db() as db:
        sector = await _sector(db)
        task = await _fetch_one(db, "SELECT task_id FROM checklist_task WHERE task_id = ?", (req.task_id,))
        if not task:
            raise HTTPException(status_code=404, detail="Tarea no encontrada.")
        cur = await db.execute(
            """
            INSERT INTO checklist_assignment
                (task_id, sector_id, username, shift, duration_minutes, allow_delay,
                 instructions_override, starts_on, active, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                req.task_id, sector["sector_id"], username, None,
                None, int(req.allow_delay), _clean(req.instructions_override) or None,
                date.today().isoformat(), int(req.active), now_iso(),
            ),
        )
        assignment_id = int(cur.lastrowid)
        await _write_schedule(db, assignment_id, req.schedule)
        after = await _assignment(db, assignment_id)
        await _audit(db, sector_id=sector["sector_id"], actor=auth["username"], action="create", entity_type="assignment", entity_id=assignment_id, after=after)
        await db.commit()
    return {"ok": True, "assignment": after}


@router.put("/admin/assignments/{assignment_id}")
async def update_assignment(assignment_id: int, req: AssignmentRequest, request: Request):
    auth = await _require_admin(request)
    username = await _validate_active_user(req.username)
    async with checklist_db() as db:
        before = await _assignment(db, assignment_id)
        task = await _fetch_one(db, "SELECT task_id FROM checklist_task WHERE task_id = ?", (req.task_id,))
        if not task:
            raise HTTPException(status_code=404, detail="Tarea no encontrada.")
        await db.execute(
            """
            UPDATE checklist_assignment SET
                task_id=?, username=?, shift=?, duration_minutes=?, allow_delay=?,
                instructions_override=?, active=?, updated_at=?
            WHERE assignment_id=?
            """,
            (
                req.task_id, username, None, None,
                int(req.allow_delay), _clean(req.instructions_override) or None,
                int(req.active), now_iso(), assignment_id,
            ),
        )
        await _write_schedule(db, assignment_id, req.schedule)
        after = await _assignment(db, assignment_id)
        await _audit(db, sector_id=before["sector_id"], actor=auth["username"], action="update", entity_type="assignment", entity_id=assignment_id, before=before, after=after)
        await db.commit()
    return {"ok": True, "assignment": after}


@router.get("/delegations")
async def delegations(request: Request):
    await _require_admin(request)
    async with checklist_db() as db:
        sector = await _sector(db)
        rows = await _fetch_all(
            db,
            """
            SELECT d.*, COUNT(da.assignment_id) assignment_count,
                   GROUP_CONCAT(t.title, ' | ') task_titles
            FROM checklist_delegation d
            LEFT JOIN checklist_delegation_assignment da ON da.delegation_id=d.delegation_id
            LEFT JOIN checklist_assignment a ON a.assignment_id=da.assignment_id
            LEFT JOIN checklist_task t ON t.task_id=a.task_id
            WHERE d.sector_id = ?
            GROUP BY d.delegation_id
            ORDER BY d.active DESC, d.date_from DESC, d.delegation_id DESC
            """,
            (sector["sector_id"],),
        )
    return {"delegations": rows}


@router.post("/admin/delegations")
async def create_delegation(req: DelegationRequest, request: Request):
    auth = await _require_admin(request)
    source = await _validate_active_user(req.from_username)
    date_from = _iso_date(req.date_from, "Fecha desde")
    date_to = _iso_date(req.date_to, "Fecha hasta")
    if date_to < date_from:
        raise HTTPException(status_code=400, detail="El rango de fechas es invalido.")
    requested: dict[int, str] = {}
    for item in req.assignments:
        if item.assignment_id in requested:
            raise HTTPException(status_code=400, detail="Una asignacion no puede distribuirse dos veces.")
        target = await _validate_active_user(item.to_username)
        if source == target:
            raise HTTPException(status_code=400, detail="Titular y reemplazo deben ser distintos.")
        requested[item.assignment_id] = target
    timestamp = now_iso()
    async with checklist_db() as db:
        sector = await _sector(db)
        placeholders = ",".join("?" for _ in requested)
        rows = await _fetch_all(
            db,
            f"""
            SELECT assignment_id FROM checklist_assignment
            WHERE sector_id=? AND username=? AND active=1 AND assignment_id IN ({placeholders})
            """,
            (sector["sector_id"], source, *requested.keys()),
        )
        valid_ids = {int(row["assignment_id"]) for row in rows}
        if valid_ids != set(requested):
            raise HTTPException(status_code=400, detail="Hay asignaciones inactivas o que no pertenecen al titular.")

        for assignment_id in requested:
            overlap = await _fetch_one(
                db,
                """
                SELECT d.delegation_id
                FROM checklist_delegation d
                WHERE d.active=1 AND d.sector_id=? AND d.from_username=?
                  AND d.date_from <= ? AND d.date_to >= ?
                  AND (
                    EXISTS (
                      SELECT 1 FROM checklist_delegation_assignment da
                      WHERE da.delegation_id=d.delegation_id AND da.assignment_id=?
                    )
                    OR NOT EXISTS (
                      SELECT 1 FROM checklist_delegation_assignment da
                      WHERE da.delegation_id=d.delegation_id
                    )
                  )
                LIMIT 1
                """,
                (sector["sector_id"], source, date_to, date_from, assignment_id),
            )
            if overlap:
                raise HTTPException(
                    status_code=409,
                    detail=f"La asignacion {assignment_id} ya esta delegada en un periodo superpuesto.",
                )

        created: list[dict[str, Any]] = []
        by_target: dict[str, list[int]] = {}
        for assignment_id, target in requested.items():
            by_target.setdefault(target, []).append(assignment_id)
        for target, assignment_ids in by_target.items():
            cur = await db.execute(
                """
                INSERT INTO checklist_delegation
                    (sector_id, from_username, to_username, date_from, date_to, active,
                     created_by, created_at, updated_by, updated_at)
                VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
                """,
                (sector["sector_id"], source, target, date_from, date_to, auth["username"], timestamp, auth["username"], timestamp),
            )
            delegation_id = int(cur.lastrowid)
            await db.executemany(
                "INSERT INTO checklist_delegation_assignment (delegation_id, assignment_id) VALUES (?, ?)",
                [(delegation_id, assignment_id) for assignment_id in assignment_ids],
            )
            after = await _fetch_one(db, "SELECT * FROM checklist_delegation WHERE delegation_id = ?", (delegation_id,))
            after["assignment_ids"] = assignment_ids
            await _audit(db, sector_id=sector["sector_id"], actor=auth["username"], action="create", entity_type="delegation", entity_id=delegation_id, after=after)
            created.append(after)
        await db.commit()
    return {"ok": True, "delegations": created}


@router.delete("/admin/delegations/{delegation_id}")
async def deactivate_delegation(delegation_id: int, request: Request):
    auth = await _require_admin(request)
    async with checklist_db() as db:
        before = await _fetch_one(db, "SELECT * FROM checklist_delegation WHERE delegation_id = ?", (delegation_id,))
        if not before:
            raise HTTPException(status_code=404, detail="Delegacion no encontrada.")
        await db.execute(
            "UPDATE checklist_delegation SET active=0, updated_by=?, updated_at=? WHERE delegation_id=?",
            (auth["username"], now_iso(), delegation_id),
        )
        after = await _fetch_one(db, "SELECT * FROM checklist_delegation WHERE delegation_id = ?", (delegation_id,))
        await _audit(db, sector_id=before["sector_id"], actor=auth["username"], action="deactivate", entity_type="delegation", entity_id=delegation_id, before=before, after=after)
        await db.commit()
    return {"ok": True}


@router.get("/admin/audit")
async def audit_log(request: Request, limit: int = Query(default=200, ge=1, le=1000)):
    await _require_admin(request)
    async with checklist_db() as db:
        rows = await _fetch_all(
            db,
            "SELECT * FROM checklist_audit ORDER BY audit_id DESC LIMIT ?",
            (limit,),
        )
    return {"audit": rows}
