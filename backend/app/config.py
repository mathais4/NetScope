"""Runtime settings, read once from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    database_url: str
    # A target is only declared DOWN after this many failed checks in a row,
    # so a single dropped packet doesn't page anyone.
    failure_threshold: int = 3
    # ...and only declared UP again after this many successes in a row,
    # so a service that is flapping doesn't open and close incidents constantly.
    recovery_threshold: int = 2
    max_concurrent_checks: int = 50
    retention_days: int = 30
    alert_webhook_url: str | None = None
    seed_demo: bool = False
    cors_origins: tuple[str, ...] = ()
    public_demo_read_only: bool = False


def load_settings() -> Settings:
    return Settings(
        database_url=os.getenv(
            "DATABASE_URL", "postgresql://netscope:netscope@localhost:5432/netscope"
        ),
        failure_threshold=int(os.getenv("FAILURE_THRESHOLD", "3")),
        recovery_threshold=int(os.getenv("RECOVERY_THRESHOLD", "2")),
        max_concurrent_checks=int(os.getenv("MAX_CONCURRENT_CHECKS", "50")),
        retention_days=int(os.getenv("RETENTION_DAYS", "30")),
        alert_webhook_url=os.getenv("ALERT_WEBHOOK_URL") or None,
        seed_demo=_bool("SEED_DEMO", False),
        public_demo_read_only=_bool("PUBLIC_DEMO_READ_ONLY", False),
        cors_origins=tuple(
            o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()
        ),
    )
