"""Runtime state adapters for ComfyGit Studio.

This module is intentionally part of the Studio runtime package, not core. The
data recorded here describes Studio sessions and runtime output history, not
portable environment truth.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SERVE_STATE_SCHEMA_VERSION = 2


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class ServeSession:
    session_id: str
    scope_key: str


@dataclass(frozen=True)
class ServeRunRecord:
    run_id: str
    session_id: str
    scope_key: str
    workflow: str
    contract: str
    status: str
    inputs: dict[str, Any]
    prompt_id: str | None = None
    raw_result: dict[str, Any] | None = None
    error: str | None = None
    created_at: str = ""
    updated_at: str = ""

    def to_public_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "run_id": self.run_id,
            "session_id": self.session_id,
            "workflow": self.workflow,
            "contract": self.contract,
            "status": self.status,
            "inputs": self.inputs,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }
        optional = {
            "prompt_id": self.prompt_id,
            "raw_result": self.raw_result,
            "error": self.error,
        }
        for key, value in optional.items():
            if value is not None:
                payload[key] = value
        return payload


@dataclass(frozen=True)
class ServeRunOutputSlot:
    slot_id: str
    run_id: str
    session_id: str
    scope_key: str
    workflow: str
    contract: str
    output_name: str
    output_type: str
    status: str
    prompt_id: str | None = None
    width: int | None = None
    height: int | None = None
    error: str | None = None
    raw_result: dict[str, Any] | None = None
    created_at: str = ""
    updated_at: str = ""

    def to_public_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "slot_id": self.slot_id,
            "run_id": self.run_id,
            "contract": f"{self.workflow} / {self.contract}",
            "contractWorkflow": self.workflow,
            "contractName": self.contract,
            "outputName": self.output_name,
            "type": self.output_type,
            "status": self.status,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }
        optional = {
            "promptId": self.prompt_id,
            "width": self.width,
            "height": self.height,
            "error": self.error,
            "rawResult": self.raw_result,
        }
        for key, value in optional.items():
            if value is not None:
                payload[key] = value
        return payload


@dataclass(frozen=True)
class ServeGalleryItem:
    item_id: str
    run_id: str
    session_id: str
    scope_key: str
    workflow: str
    contract: str
    status: str
    output_type: str
    inputs: dict[str, Any]
    slot_id: str | None = None
    output_name: str | None = None
    prompt_id: str | None = None
    filename: str | None = None
    url: str | None = None
    width: int | None = None
    height: int | None = None
    artifact: dict[str, Any] | None = None
    raw_result: dict[str, Any] | None = None
    error: str | None = None
    created_at: str = ""
    updated_at: str = ""

    def to_public_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.item_id,
            "run_id": self.run_id,
            "contract": f"{self.workflow} / {self.contract}",
            "contractWorkflow": self.workflow,
            "contractName": self.contract,
            "status": self.status,
            "type": self.output_type,
            "inputs": self.inputs,
            "createdAt": self.created_at,
        }
        optional = {
            "slotId": self.slot_id,
            "promptId": self.prompt_id,
            "outputName": self.output_name,
            "filename": self.filename,
            "url": self.url,
            "width": self.width,
            "height": self.height,
            "artifact": self.artifact,
            "rawResult": self.raw_result,
            "error": self.error,
        }
        for key, value in optional.items():
            if value is not None:
                payload[key] = value
        return payload


class ServeStateStore:
    """Interface for serve-owned session/run/gallery runtime state."""

    persistent = False

    def close(self) -> None:
        return None

    def ensure_session(self, session_id: str, *, scope_key: str) -> ServeSession:
        raise NotImplementedError

    def record_run(self, run: ServeRunRecord) -> None:
        raise NotImplementedError

    def get_run(self, scope_key: str, run_id: str) -> dict[str, Any] | None:
        raise NotImplementedError

    def get_run_record(self, run_id: str) -> ServeRunRecord | None:
        raise NotImplementedError

    def list_runs(self, scope_key: str, statuses: set[str] | None = None) -> list[dict[str, Any]]:
        raise NotImplementedError

    def list_active_runs(self, statuses: set[str]) -> list[ServeRunRecord]:
        raise NotImplementedError

    def cancel_run(self, scope_key: str, run_id: str, *, raw_result: dict[str, Any], error: str) -> bool:
        raise NotImplementedError

    def record_output_slots(self, slots: list[ServeRunOutputSlot]) -> None:
        raise NotImplementedError

    def list_output_slots(self, scope_key: str, run_id: str) -> list[dict[str, Any]]:
        raise NotImplementedError

    def record_gallery_items(self, items: list[ServeGalleryItem]) -> None:
        raise NotImplementedError

    def list_gallery_items(self, scope_key: str) -> list[dict[str, Any]]:
        raise NotImplementedError

    def list_gallery_items_for_run(self, scope_key: str, run_id: str) -> list[dict[str, Any]]:
        raise NotImplementedError

    def delete_gallery_item(self, scope_key: str, item_id: str) -> bool:
        raise NotImplementedError


class EphemeralServeStateStore(ServeStateStore):
    """In-memory serve state discarded when the process exits."""

    def __init__(self) -> None:
        self.sessions: dict[str, ServeSession] = {}
        self.runs: dict[str, ServeRunRecord] = {}
        self.output_slots: dict[str, ServeRunOutputSlot] = {}
        self.gallery_items: dict[str, ServeGalleryItem] = {}

    def ensure_session(self, session_id: str, *, scope_key: str) -> ServeSession:
        session = self.sessions.get(session_id) or ServeSession(session_id=session_id, scope_key=scope_key)
        self.sessions[session_id] = session
        return session

    def record_run(self, run: ServeRunRecord) -> None:
        self.runs[run.run_id] = _with_run_timestamps(run)

    def get_run(self, scope_key: str, run_id: str) -> dict[str, Any] | None:
        run = self.runs.get(run_id)
        if run is None or run.scope_key != scope_key:
            return None
        return run.to_public_dict()

    def get_run_record(self, run_id: str) -> ServeRunRecord | None:
        return self.runs.get(run_id)

    def list_runs(self, scope_key: str, statuses: set[str] | None = None) -> list[dict[str, Any]]:
        runs = [run for run in self.runs.values() if run.scope_key == scope_key]
        if statuses is not None:
            runs = [run for run in runs if run.status in statuses]
        runs.sort(key=lambda run: run.created_at, reverse=True)
        return [run.to_public_dict() for run in runs]

    def list_active_runs(self, statuses: set[str]) -> list[ServeRunRecord]:
        runs = [run for run in self.runs.values() if run.status in statuses]
        runs.sort(key=lambda run: run.created_at, reverse=True)
        return runs

    def cancel_run(self, scope_key: str, run_id: str, *, raw_result: dict[str, Any], error: str) -> bool:
        run = self.runs.get(run_id)
        if run is None or run.scope_key != scope_key or run.status not in {"submitted", "running"}:
            return False
        self.runs[run_id] = _with_run_timestamps(
            ServeRunRecord(
                run_id=run.run_id,
                session_id=run.session_id,
                scope_key=run.scope_key,
                workflow=run.workflow,
                contract=run.contract,
                status="cancelled",
                inputs=run.inputs,
                prompt_id=run.prompt_id,
                raw_result=raw_result,
                error=error,
                created_at=run.created_at,
            )
        )
        for slot_id, slot in list(self.output_slots.items()):
            if slot.scope_key == scope_key and slot.run_id == run_id and slot.status in {"pending", "running"}:
                self.output_slots[slot_id] = _with_output_slot_timestamps(
                    ServeRunOutputSlot(
                        slot_id=slot.slot_id,
                        run_id=slot.run_id,
                        session_id=slot.session_id,
                        scope_key=slot.scope_key,
                        workflow=slot.workflow,
                        contract=slot.contract,
                        output_name=slot.output_name,
                        output_type=slot.output_type,
                        status="cancelled",
                        prompt_id=slot.prompt_id,
                        width=slot.width,
                        height=slot.height,
                        error=error,
                        raw_result=raw_result,
                        created_at=slot.created_at,
                    )
                )
        for item_id, item in list(self.gallery_items.items()):
            if item.scope_key == scope_key and item.run_id == run_id and item.status == "pending":
                del self.gallery_items[item_id]
        return True

    def record_output_slots(self, slots: list[ServeRunOutputSlot]) -> None:
        for slot in slots:
            stamped = _with_output_slot_timestamps(slot)
            self.output_slots[stamped.slot_id] = stamped

    def list_output_slots(self, scope_key: str, run_id: str) -> list[dict[str, Any]]:
        slots = [
            slot
            for slot in self.output_slots.values()
            if slot.scope_key == scope_key and slot.run_id == run_id
        ]
        slots.sort(key=lambda slot: slot.created_at)
        return [slot.to_public_dict() for slot in slots]

    def record_gallery_items(self, items: list[ServeGalleryItem]) -> None:
        for item in items:
            stamped = _with_gallery_timestamps(item)
            self.gallery_items[stamped.item_id] = stamped

    def list_gallery_items(self, scope_key: str) -> list[dict[str, Any]]:
        items = [item for item in self.gallery_items.values() if item.scope_key == scope_key]
        items.sort(key=lambda item: item.created_at, reverse=True)
        return [item.to_public_dict() for item in items]

    def list_gallery_items_for_run(self, scope_key: str, run_id: str) -> list[dict[str, Any]]:
        items = [
            item
            for item in self.gallery_items.values()
            if item.scope_key == scope_key and item.run_id == run_id
        ]
        items.sort(key=lambda item: item.created_at, reverse=True)
        return [item.to_public_dict() for item in items]

    def delete_gallery_item(self, scope_key: str, item_id: str) -> bool:
        item = self.gallery_items.get(item_id)
        if item is None or item.scope_key != scope_key:
            return False
        del self.gallery_items[item_id]
        return True


class SQLiteServeStateStore(ServeStateStore):
    """SQLite-backed serve state for local persistent Studio sessions."""

    persistent = True

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.database_path)
        self.connection.row_factory = sqlite3.Row
        self._init_schema()

    def close(self) -> None:
        self.connection.close()

    def ensure_session(self, session_id: str, *, scope_key: str) -> ServeSession:
        now = utc_now()
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO sessions (session_id, scope_key, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    scope_key = excluded.scope_key,
                    updated_at = excluded.updated_at
                """,
                (session_id, scope_key, now, now),
            )
        return ServeSession(session_id=session_id, scope_key=scope_key)

    def record_run(self, run: ServeRunRecord) -> None:
        run = _with_run_timestamps(run)
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO runs (
                    run_id, session_id, scope_key, workflow, contract, status,
                    prompt_id, inputs_json, raw_result_json, error, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    status = excluded.status,
                    prompt_id = excluded.prompt_id,
                    raw_result_json = excluded.raw_result_json,
                    inputs_json = excluded.inputs_json,
                    error = excluded.error,
                    updated_at = excluded.updated_at
                """,
                (
                    run.run_id,
                    run.session_id,
                    run.scope_key,
                    run.workflow,
                    run.contract,
                    run.status,
                    run.prompt_id,
                    _json(run.inputs),
                    _json(run.raw_result),
                    run.error,
                    run.created_at,
                    run.updated_at,
                ),
            )

    def get_run(self, scope_key: str, run_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM runs
            WHERE scope_key = ? AND run_id = ?
            """,
            (scope_key, run_id),
        ).fetchone()
        return _run_from_row(row).to_public_dict() if row else None

    def get_run_record(self, run_id: str) -> ServeRunRecord | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM runs
            WHERE run_id = ?
            """,
            (run_id,),
        ).fetchone()
        return _run_from_row(row) if row else None

    def list_runs(self, scope_key: str, statuses: set[str] | None = None) -> list[dict[str, Any]]:
        params: list[Any] = [scope_key]
        status_clause = ""
        if statuses:
            placeholders = ", ".join("?" for _ in statuses)
            status_clause = f" AND status IN ({placeholders})"
            params.extend(sorted(statuses))
        rows = self.connection.execute(
            f"""
            SELECT *
            FROM runs
            WHERE scope_key = ?{status_clause}
            ORDER BY created_at DESC, run_id DESC
            """,
            params,
        ).fetchall()
        return [_run_from_row(row).to_public_dict() for row in rows]

    def list_active_runs(self, statuses: set[str]) -> list[ServeRunRecord]:
        if not statuses:
            return []
        placeholders = ", ".join("?" for _ in statuses)
        rows = self.connection.execute(
            f"""
            SELECT *
            FROM runs
            WHERE status IN ({placeholders})
            ORDER BY created_at DESC, run_id DESC
            """,
            sorted(statuses),
        ).fetchall()
        return [_run_from_row(row) for row in rows]

    def cancel_run(self, scope_key: str, run_id: str, *, raw_result: dict[str, Any], error: str) -> bool:
        now = utc_now()
        with self.connection:
            cursor = self.connection.execute(
                """
                UPDATE runs
                SET status = 'cancelled',
                    raw_result_json = ?,
                    error = ?,
                    updated_at = ?
                WHERE scope_key = ?
                    AND run_id = ?
                    AND status IN ('submitted', 'running')
                """,
                (_json(raw_result), error, now, scope_key, run_id),
            )
            if cursor.rowcount == 0:
                return False
            self.connection.execute(
                """
                UPDATE output_slots
                SET status = 'cancelled',
                    raw_result_json = ?,
                    error = ?,
                    updated_at = ?
                WHERE scope_key = ?
                    AND run_id = ?
                    AND status IN ('pending', 'running')
                """,
                (_json(raw_result), error, now, scope_key, run_id),
            )
            self.connection.execute(
                """
                DELETE FROM gallery_items
                WHERE scope_key = ?
                    AND run_id = ?
                    AND status = 'pending'
                """,
                (scope_key, run_id),
            )
        return True

    def record_output_slots(self, slots: list[ServeRunOutputSlot]) -> None:
        with self.connection:
            for slot in slots:
                slot = _with_output_slot_timestamps(slot)
                self.connection.execute(
                    """
                    INSERT INTO output_slots (
                        slot_id, run_id, session_id, scope_key, workflow, contract,
                        output_name, output_type, status, prompt_id, width, height,
                        error, raw_result_json, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(slot_id) DO UPDATE SET
                        status = excluded.status,
                        prompt_id = excluded.prompt_id,
                        width = excluded.width,
                        height = excluded.height,
                        error = excluded.error,
                        raw_result_json = excluded.raw_result_json,
                        updated_at = excluded.updated_at
                    """,
                    (
                        slot.slot_id,
                        slot.run_id,
                        slot.session_id,
                        slot.scope_key,
                        slot.workflow,
                        slot.contract,
                        slot.output_name,
                        slot.output_type,
                        slot.status,
                        slot.prompt_id,
                        slot.width,
                        slot.height,
                        slot.error,
                        _json(slot.raw_result),
                        slot.created_at,
                        slot.updated_at,
                    ),
                )

    def list_output_slots(self, scope_key: str, run_id: str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM output_slots
            WHERE scope_key = ? AND run_id = ?
            ORDER BY created_at ASC, slot_id ASC
            """,
            (scope_key, run_id),
        ).fetchall()
        return [_output_slot_from_row(row).to_public_dict() for row in rows]

    def record_gallery_items(self, items: list[ServeGalleryItem]) -> None:
        with self.connection:
            for item in items:
                item = _with_gallery_timestamps(item)
                self.connection.execute(
                    """
                    INSERT INTO gallery_items (
                        item_id, run_id, session_id, scope_key, workflow, contract,
                        status, output_type, slot_id, output_name, prompt_id, filename, url,
                        width, height, inputs_json, artifact_json, raw_result_json,
                        error, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(item_id) DO UPDATE SET
                        status = excluded.status,
                        output_type = excluded.output_type,
                        slot_id = excluded.slot_id,
                        output_name = excluded.output_name,
                        prompt_id = excluded.prompt_id,
                        filename = excluded.filename,
                        url = excluded.url,
                        width = excluded.width,
                        height = excluded.height,
                        inputs_json = excluded.inputs_json,
                        artifact_json = excluded.artifact_json,
                        raw_result_json = excluded.raw_result_json,
                        error = excluded.error,
                        updated_at = excluded.updated_at
                    """,
                    (
                        item.item_id,
                        item.run_id,
                        item.session_id,
                        item.scope_key,
                        item.workflow,
                        item.contract,
                        item.status,
                        item.output_type,
                        item.slot_id,
                        item.output_name,
                        item.prompt_id,
                        item.filename,
                        item.url,
                        item.width,
                        item.height,
                        _json(item.inputs),
                        _json(item.artifact),
                        _json(item.raw_result),
                        item.error,
                        item.created_at,
                        item.updated_at,
                    ),
                )

    def list_gallery_items(self, scope_key: str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM gallery_items
            WHERE scope_key = ?
            ORDER BY created_at DESC, item_id DESC
            """,
            (scope_key,),
        ).fetchall()
        return [_gallery_item_from_row(row).to_public_dict() for row in rows]

    def list_gallery_items_for_run(self, scope_key: str, run_id: str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM gallery_items
            WHERE scope_key = ? AND run_id = ?
            ORDER BY created_at DESC, item_id DESC
            """,
            (scope_key, run_id),
        ).fetchall()
        return [_gallery_item_from_row(row).to_public_dict() for row in rows]

    def delete_gallery_item(self, scope_key: str, item_id: str) -> bool:
        with self.connection:
            cursor = self.connection.execute(
                "DELETE FROM gallery_items WHERE scope_key = ? AND item_id = ?",
                (scope_key, item_id),
            )
        return cursor.rowcount > 0

    def _init_schema(self) -> None:
        with self.connection:
            self.connection.execute("PRAGMA journal_mode=WAL")
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS serve_state_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            self.connection.execute(
                """
                INSERT INTO serve_state_meta (key, value)
                VALUES ('schema_version', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (str(SERVE_STATE_SCHEMA_VERSION),),
            )
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    scope_key TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    scope_key TEXT NOT NULL,
                    workflow TEXT NOT NULL,
                    contract TEXT NOT NULL,
                    status TEXT NOT NULL,
                    prompt_id TEXT,
                    inputs_json TEXT NOT NULL,
                    raw_result_json TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS gallery_items (
                    item_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    scope_key TEXT NOT NULL,
                    workflow TEXT NOT NULL,
                    contract TEXT NOT NULL,
                    status TEXT NOT NULL,
                    output_type TEXT NOT NULL,
                    slot_id TEXT,
                    output_name TEXT,
                    prompt_id TEXT,
                    filename TEXT,
                    url TEXT,
                    width INTEGER,
                    height INTEGER,
                    inputs_json TEXT NOT NULL,
                    artifact_json TEXT,
                    raw_result_json TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS output_slots (
                    slot_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    scope_key TEXT NOT NULL,
                    workflow TEXT NOT NULL,
                    contract TEXT NOT NULL,
                    output_name TEXT NOT NULL,
                    output_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    prompt_id TEXT,
                    width INTEGER,
                    height INTEGER,
                    error TEXT,
                    raw_result_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._ensure_column("gallery_items", "slot_id", "TEXT")
            self.connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_gallery_items_scope_created ON gallery_items(scope_key, created_at DESC)"
            )
            self.connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_gallery_items_scope_run ON gallery_items(scope_key, run_id)"
            )
            self.connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_runs_scope_status_created ON runs(scope_key, status, created_at DESC)"
            )
            self.connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_output_slots_scope_run ON output_slots(scope_key, run_id)"
            )

    def _ensure_column(self, table_name: str, column_name: str, declaration: str) -> None:
        rows = self.connection.execute(f"PRAGMA table_info({table_name})").fetchall()
        if any(row["name"] == column_name for row in rows):
            return
        self.connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {declaration}")


def _with_run_timestamps(run: ServeRunRecord) -> ServeRunRecord:
    now = utc_now()
    created_at = run.created_at or now
    return ServeRunRecord(
        run_id=run.run_id,
        session_id=run.session_id,
        scope_key=run.scope_key,
        workflow=run.workflow,
        contract=run.contract,
        status=run.status,
        inputs=run.inputs,
        prompt_id=run.prompt_id,
        raw_result=run.raw_result,
        error=run.error,
        created_at=created_at,
        updated_at=run.updated_at or now,
    )


def _with_output_slot_timestamps(slot: ServeRunOutputSlot) -> ServeRunOutputSlot:
    now = utc_now()
    created_at = slot.created_at or now
    return ServeRunOutputSlot(
        slot_id=slot.slot_id,
        run_id=slot.run_id,
        session_id=slot.session_id,
        scope_key=slot.scope_key,
        workflow=slot.workflow,
        contract=slot.contract,
        output_name=slot.output_name,
        output_type=slot.output_type,
        status=slot.status,
        prompt_id=slot.prompt_id,
        width=slot.width,
        height=slot.height,
        error=slot.error,
        raw_result=slot.raw_result,
        created_at=created_at,
        updated_at=slot.updated_at or now,
    )


def _with_gallery_timestamps(item: ServeGalleryItem) -> ServeGalleryItem:
    now = utc_now()
    created_at = item.created_at or now
    return ServeGalleryItem(
        item_id=item.item_id,
        run_id=item.run_id,
        session_id=item.session_id,
        scope_key=item.scope_key,
        workflow=item.workflow,
        contract=item.contract,
        status=item.status,
        output_type=item.output_type,
        inputs=item.inputs,
        slot_id=item.slot_id,
        output_name=item.output_name,
        prompt_id=item.prompt_id,
        filename=item.filename,
        url=item.url,
        width=item.width,
        height=item.height,
        artifact=item.artifact,
        raw_result=item.raw_result,
        error=item.error,
        created_at=created_at,
        updated_at=item.updated_at or now,
    )


def _output_slot_from_row(row: sqlite3.Row) -> ServeRunOutputSlot:
    return ServeRunOutputSlot(
        slot_id=str(row["slot_id"]),
        run_id=str(row["run_id"]),
        session_id=str(row["session_id"]),
        scope_key=str(row["scope_key"]),
        workflow=str(row["workflow"]),
        contract=str(row["contract"]),
        output_name=str(row["output_name"]),
        output_type=str(row["output_type"]),
        status=str(row["status"]),
        prompt_id=row["prompt_id"],
        width=row["width"],
        height=row["height"],
        error=row["error"],
        raw_result=_loads(row["raw_result_json"], None),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _gallery_item_from_row(row: sqlite3.Row) -> ServeGalleryItem:
    return ServeGalleryItem(
        item_id=str(row["item_id"]),
        run_id=str(row["run_id"]),
        session_id=str(row["session_id"]),
        scope_key=str(row["scope_key"]),
        workflow=str(row["workflow"]),
        contract=str(row["contract"]),
        status=str(row["status"]),
        output_type=str(row["output_type"]),
        slot_id=_row_value(row, "slot_id"),
        output_name=row["output_name"],
        prompt_id=row["prompt_id"],
        filename=row["filename"],
        url=row["url"],
        width=row["width"],
        height=row["height"],
        inputs=_loads(row["inputs_json"], {}),
        artifact=_loads(row["artifact_json"], None),
        raw_result=_loads(row["raw_result_json"], None),
        error=row["error"],
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _run_from_row(row: sqlite3.Row) -> ServeRunRecord:
    return ServeRunRecord(
        run_id=str(row["run_id"]),
        session_id=str(row["session_id"]),
        scope_key=str(row["scope_key"]),
        workflow=str(row["workflow"]),
        contract=str(row["contract"]),
        status=str(row["status"]),
        prompt_id=row["prompt_id"],
        inputs=_loads(row["inputs_json"], {}),
        raw_result=_loads(row["raw_result_json"], None),
        error=row["error"],
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _json(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def _row_value(row: sqlite3.Row, key: str) -> Any:
    return row[key] if key in row.keys() else None
