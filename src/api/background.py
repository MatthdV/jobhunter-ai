"""Background task state tracker for pipeline phases.

Multi-tenant aware: all public methods accept an optional ``user_id`` parameter.

State is persisted to the ``pipeline_runs`` table (one row per user+phase) so
that phase status survives Railway redeploys. An earlier version kept state in
an in-memory dict, which was wiped on every deploy, leaving the UI showing a
stale "running" forever.

CLI mode passes ``user_id=0`` (the default), which is safe because no real
user will ever have id=0 (SQLite autoincrement starts at 1).
"""

import asyncio
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from src.storage.database import get_session
from src.storage.models import PipelineRun

_PHASES = ("scan", "match", "apply", "respond")

# user_id used by CLI / non-authenticated callers
_CLI_USER_ID = 0


class TaskStatus(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"


_IDLE_STATE: dict[str, Any] = {
    "status": TaskStatus.IDLE,
    "started_at": None,
    "finished_at": None,
    "result": None,
    "error": None,
}


class TaskTracker:
    """DB-backed tracker for pipeline phase execution.

    Public API is unchanged from the previous in-memory version
    (try_start / start / done / error / get / all / is_running) so callers
    need no modification. Only the storage backend moved to ``pipeline_runs``.

    One asyncio.Lock per (user_id, phase) key makes the is_running() check and
    the RUNNING transition atomic within the process. The locks are in-memory
    only — they don't need to survive a redeploy, since a redeploy kills the
    running task anyway (reconciled to ERROR at startup).
    """

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _key(user_id: int, phase: str) -> str:
        return f"{user_id}:{phase}"

    def _get_lock(self, key: str) -> asyncio.Lock:
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self._locks[key]

    @staticmethod
    def _upsert(
        user_id: int,
        phase: str,
        *,
        status: str,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        result_json: str | None = None,
        error: str | None = None,
        touch_started: bool = False,
    ) -> None:
        """Insert or update the single PipelineRun row for (user_id, phase)."""
        with get_session() as session:
            row = (
                session.query(PipelineRun)
                .filter(PipelineRun.user_id == user_id, PipelineRun.phase == phase)
                .one_or_none()
            )
            if row is None:
                row = PipelineRun(user_id=user_id, phase=phase, status=status)
                session.add(row)
            row.status = status  # type: ignore[assignment]
            if touch_started:
                row.started_at = started_at  # type: ignore[assignment]
                row.finished_at = None  # type: ignore[assignment]
                row.result_json = None  # type: ignore[assignment]
                row.error = None  # type: ignore[assignment]
            if finished_at is not None:
                row.finished_at = finished_at  # type: ignore[assignment]
            if result_json is not None:
                row.result_json = result_json  # type: ignore[assignment]
            if error is not None:
                row.error = error  # type: ignore[assignment]

    # ------------------------------------------------------------------
    # Public API (all methods accept user_id, default = CLI sentinel)
    # ------------------------------------------------------------------

    async def try_start(self, phase: str, user_id: int = _CLI_USER_ID) -> bool:
        """Atomically check-and-set RUNNING. Returns True if started, False if already running."""
        key = self._key(user_id, phase)
        lock = self._get_lock(key)
        async with lock:
            if self.is_running(phase, user_id):
                return False
            self.start(phase, user_id)
            return True

    def start(self, phase: str, user_id: int = _CLI_USER_ID) -> None:
        """Mark phase RUNNING. Prefer try_start() for the atomic check."""
        self._upsert(
            user_id,
            phase,
            status=TaskStatus.RUNNING,
            started_at=datetime.now(UTC),
            touch_started=True,
        )

    def done(self, phase: str, user_id: int = _CLI_USER_ID, result: Any = None) -> None:
        self._upsert(
            user_id,
            phase,
            status=TaskStatus.DONE,
            finished_at=datetime.now(UTC),
            result_json=json.dumps(result) if result is not None else None,
        )

    def error(self, phase: str, msg: str, user_id: int = _CLI_USER_ID) -> None:
        self._upsert(
            user_id,
            phase,
            status=TaskStatus.ERROR,
            finished_at=datetime.now(UTC),
            error=msg,
        )

    def get(self, phase: str, user_id: int = _CLI_USER_ID) -> dict[str, Any]:
        with get_session() as session:
            row = (
                session.query(PipelineRun)
                .filter(PipelineRun.user_id == user_id, PipelineRun.phase == phase)
                .one_or_none()
            )
            if row is None:
                return dict(_IDLE_STATE)
            result: Any = None
            if row.result_json:
                try:
                    result = json.loads(row.result_json)
                except (json.JSONDecodeError, TypeError):
                    result = None
            return {
                "status": row.status,
                "started_at": row.started_at.isoformat() if row.started_at else None,
                "finished_at": row.finished_at.isoformat() if row.finished_at else None,
                "result": result,
                "error": row.error,
            }

    def all(self, user_id: int = _CLI_USER_ID) -> dict[str, dict[str, Any]]:
        """Return status dict for all phases for the given user."""
        return {phase: self.get(phase, user_id) for phase in _PHASES}

    def is_running(self, phase: str, user_id: int = _CLI_USER_ID) -> bool:
        return self.get(phase, user_id)["status"] == TaskStatus.RUNNING

    def reset(self) -> None:
        """Delete all persisted phase state. For tests / a clean slate."""
        self._locks.clear()
        with get_session() as session:
            session.query(PipelineRun).delete()


def reconcile_orphaned_runs() -> int:
    """Mark any RUNNING phase as ERROR — called once at startup.

    A row left RUNNING means the process died (redeploy/crash) mid-phase; the
    task is gone, so the status is a lie. Flip it to ERROR so the UI shows
    reality. Returns the number of rows reconciled.
    """
    with get_session() as session:
        rows = (
            session.query(PipelineRun)
            .filter(PipelineRun.status == TaskStatus.RUNNING)
            .all()
        )
        for row in rows:
            row.status = TaskStatus.ERROR  # type: ignore[assignment]
            row.finished_at = datetime.now(UTC)  # type: ignore[assignment]
            row.error = "Interrompu par un redéploiement"  # type: ignore[assignment]
        return len(rows)


# Singleton used by all routes
tracker = TaskTracker()
