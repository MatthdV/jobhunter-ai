"""Background task state tracker for pipeline phases."""

from datetime import datetime
from enum import StrEnum
from typing import Any


class TaskStatus(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"


class TaskTracker:
    """Simple in-memory tracker for pipeline phase execution."""

    def __init__(self) -> None:
        self._tasks: dict[str, dict[str, Any]] = {}

    def start(self, name: str) -> None:
        self._tasks[name] = {
            "status": TaskStatus.RUNNING,
            "started_at": datetime.utcnow().isoformat(),
            "finished_at": None,
            "result": None,
            "error": None,
        }

    def done(self, name: str, result: Any = None) -> None:
        if name not in self._tasks:
            self._tasks[name] = {}
        self._tasks[name].update(
            {
                "status": TaskStatus.DONE,
                "finished_at": datetime.utcnow().isoformat(),
                "result": result,
                "error": None,
            }
        )

    def error(self, name: str, msg: str) -> None:
        if name not in self._tasks:
            self._tasks[name] = {}
        self._tasks[name].update(
            {
                "status": TaskStatus.ERROR,
                "finished_at": datetime.utcnow().isoformat(),
                "error": msg,
            }
        )

    def get(self, name: str) -> dict[str, Any]:
        return self._tasks.get(
            name,
            {
                "status": TaskStatus.IDLE,
                "started_at": None,
                "finished_at": None,
                "result": None,
                "error": None,
            },
        )

    def all(self) -> dict[str, dict[str, Any]]:
        phases = ["scan", "match", "apply", "respond"]
        return {phase: self.get(phase) for phase in phases}

    def is_running(self, name: str) -> bool:
        return self.get(name)["status"] == TaskStatus.RUNNING


# Singleton used by all routes
tracker = TaskTracker()
