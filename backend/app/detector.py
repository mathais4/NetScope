"""Outage detection: turns a stream of check results into incidents.

A target is only declared DOWN after `failure_threshold` consecutive failures,
and only UP again after `recovery_threshold` consecutive successes. This is
hysteresis: it stops one lost packet from raising an alert, and stops a
service that alternates pass/fail from opening and closing incidents on
every check.

This class is pure in-memory logic with no I/O, so it is easy to test.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from .models import CheckResult, IncidentEvent

Status = Literal["unknown", "up", "degraded", "down"]


@dataclass
class _State:
    down: bool = False
    seen_any: bool = False
    fails: int = 0
    oks: int = 0
    first_fail_at: datetime | None = None
    first_ok_at: datetime | None = None
    last_error: str | None = None


class IncidentDetector:
    def __init__(self, failure_threshold: int = 3, recovery_threshold: int = 2) -> None:
        if failure_threshold < 1 or recovery_threshold < 1:
            raise ValueError("thresholds must be at least 1")
        self.failure_threshold = failure_threshold
        self.recovery_threshold = recovery_threshold
        self._states: dict[int, _State] = {}

    def restore_down(self, target_id: int) -> None:
        """Called at startup for targets with an open incident in the database,
        so a restart doesn't forget that something is down (or alert twice)."""
        self._states[target_id] = _State(down=True, seen_any=True)

    def forget(self, target_id: int) -> None:
        self._states.pop(target_id, None)

    def status(self, target_id: int) -> Status:
        s = self._states.get(target_id)
        if s is None or not s.seen_any:
            return "unknown"
        if s.down:
            return "down"
        if s.fails > 0:
            return "degraded"  # failing, but not yet long enough to call it an outage
        return "up"

    def observe(self, result: CheckResult) -> IncidentEvent | None:
        s = self._states.setdefault(result.target_id, _State())
        s.seen_any = True

        if result.ok:
            if s.oks == 0:
                s.first_ok_at = result.checked_at
            s.oks += 1
            s.fails = 0
            s.first_fail_at = None
            if s.down and s.oks >= self.recovery_threshold:
                s.down = False
                return IncidentEvent(
                    "resolved", result.target_id, s.first_ok_at or result.checked_at,
                    result.checked_at,
                )
            return None

        if s.fails == 0:
            s.first_fail_at = result.checked_at
        s.fails += 1
        s.oks = 0
        s.first_ok_at = None
        s.last_error = result.error
        if not s.down and s.fails >= self.failure_threshold:
            s.down = True
            return IncidentEvent(
                "opened", result.target_id, s.first_fail_at or result.checked_at,
                result.checked_at, cause=result.error,
            )
        return None
