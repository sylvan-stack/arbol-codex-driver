"""Monotonic run limits; caller limits never use the conformance time scale."""

from typing import cast

from .errors import Failure
from .json_types import Object


class RunClocks:
    def __init__(self, started_at: float, start_seconds: float, limits: Object | None) -> None:
        self.started_at = started_at
        self.start_seconds = start_seconds
        limits = limits or {}
        self.idle_seconds = float(cast(int | float, limits.get("idleSeconds", 900)))
        total = limits.get("totalSeconds")
        self.total_seconds = float(total) if isinstance(total, (int, float)) else None
        self.acknowledged = False
        self.last_life = started_at
        self.paused_at: float | None = None

    def acknowledge(self, at: float) -> None:
        self.acknowledged = True
        self.last_life = at

    def check(self, at: float, last_notification: float, busy: bool) -> Failure | None:
        self.last_life = max(self.last_life, last_notification)
        limit: str | None = None
        if self.total_seconds is not None and at - self.started_at >= self.total_seconds:
            limit = "total"
        elif not self.acknowledged and at - self.started_at >= self.start_seconds:
            limit = "start"
        elif self.acknowledged:
            if busy:
                if self.paused_at is None:
                    self.paused_at = at
            else:
                if self.paused_at is not None:
                    # Busy time consumes none of the idle budget.
                    self.last_life += at - self.paused_at
                    self.last_life = min(at, self.last_life)
                    self.paused_at = None
                if self.idle_seconds > 0 and at - self.last_life >= self.idle_seconds:
                    limit = "idle"
        return None if limit is None else Failure(
            "limit_reached", f"The run reached its {limit} time limit.",
            {"detail": {"basis": "fields", "limit": limit}},
        )
