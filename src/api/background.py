"""Background task state tracker for pipeline phases.

Multi-tenant aware: all public methods accept an optional ``user_id`` parameter.
The internal key is ``f"{user_id}:{phase}"`` so each user's phases are fully
isolated in the shared in-memory dict.

CLI mode passes ``user_id=0`` (the default), which is safe because no real
user will ever have id=0 (SQLite autoincrement starts at 1).
"""

import asyncio
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

_PHASES = ("scan", "match", "apply", "respond")

# user_id used by CLI / non-authenticated callers
_CLI_USER_ID = 0


class TaskStatus(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"


class TaskTracker:
    """In-memory tracker for pipeline phase execution.

    Uses one asyncio.Lock per (user_id, phase) key so that the is_running()
    check and state transition are atomic.  Two concurrent POST requests from
    the same user cannot both start the same phase.
    """

    def __init__(self) -> None:
        self._tasks: dict[str, dict[str, Any]] = {}
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
            self._tasks[key] = {
                "status": TaskStatus.RUNNING,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "finished_at": None,
                "result": None,
                "error": None,
            }
            return True

    def start(self, phase: str, user_id: int = _CLI_USER_ID) -> None:
        """Non-atomic start — kept for backward compat. Prefer try_start()."""
        key = self._key(user_id, phase)
        self._tasks[key] = {
            "status": TaskStatus.RUNNING,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None,
            "result": None,
            "error": None,
        }

    def done(self, phase: str, user_id: int = _CLI_USER_ID, result: Any = None) -> None:
        key = self._key(user_id, phase)
        if key not in self._tasks:
            self._tasks[key] = {}
        self._tasks[key].update(
            {
                "status": TaskStatus.DONE,
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "result": result,
                "error": None,
            }
        )

    def error(self, phase: str, msg: str, user_id: int = _CLI_USER_ID) -> None:
        key = self._key(user_id, phase)
        if key not in self._tasks:
            self._tasks[key] = {}
        self._tasks[key].update(
            {
                "status": TaskStatus.ERROR,
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "error": msg,
            }
        )

    def get(self, phase: str, user_id: int = _CLI_USER_ID) -> dict[str, Any]:
        key = self._key(user_id, phase)
        return self._tasks.get(
            key,
            {
                "status": TaskStatus.IDLE,
                "started_at": None,
                "finished_at": None,
                "result": None,
                "error": None,
            },
        )

    def all(self, user_id: int = _CLI_USER_ID) -> dict[str, dict[str, Any]]:
        """Return status dict for all phases for the given user."""
        return {phase: self.get(phase, user_id) for phase in _PHASES}

    def is_running(self, phase: str, user_id: int = _CLI_USER_ID) -> bool:
        return self.get(phase, user_id)["status"] == TaskStatus.RUNNING


# Singleton used by all routes
tracker = TaskTracker()
