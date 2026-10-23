"""Plain domain objects shared by the checker, detector, scheduler and store.

These deliberately have no database or web-framework code in them, so the
monitoring logic can be unit-tested without PostgreSQL or FastAPI.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

CheckKind = Literal["http", "tcp", "ping"]


@dataclass(frozen=True)
class Target:
    id: int
    name: str
    kind: CheckKind
    url: str | None = None  # http targets
    host: str | None = None  # tcp and ping targets
    port: int | None = None  # tcp targets
    interval_s: int = 30
    timeout_s: float = 5.0
    expected_status: int | None = None  # http: None means "any 2xx or 3xx"
    enabled: bool = True

    @property
    def address(self) -> str:
        if self.kind == "http":
            return self.url or ""
        if self.kind == "tcp":
            return f"{self.host}:{self.port}"
        return self.host or ""


@dataclass(frozen=True)
class Outcome:
    """What a single probe observed."""

    ok: bool
    latency_ms: float | None = None
    status_code: int | None = None
    error: str | None = None


@dataclass(frozen=True)
class CheckResult:
    """An Outcome tied to a target and a point in time; one row in check_results."""

    target_id: int
    checked_at: datetime
    ok: bool
    latency_ms: float | None = None
    status_code: int | None = None
    error: str | None = None

    @classmethod
    def from_outcome(cls, target_id: int, at: datetime, o: Outcome) -> "CheckResult":
        return cls(target_id, at, o.ok, o.latency_ms, o.status_code, o.error)


@dataclass(frozen=True)
class IncidentEvent:
    kind: Literal["opened", "resolved"]
    target_id: int
    # For "opened": when the first failing check in the streak happened (the real
    # start of the outage), not when we became sure about it.
    # For "resolved": when the first successful check in the recovery streak happened.
    at: datetime
    detected_at: datetime
    cause: str | None = None
