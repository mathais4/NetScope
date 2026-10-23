"""PostgreSQL access through an asyncpg connection pool. Plain SQL, no ORM:
every query is in queries.py and can be read (and EXPLAINed) as-is."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import asyncpg

from . import queries as q
from .models import CheckResult, Target

SCHEMA = (Path(__file__).parent / "schema.sql").read_text()


def _target(row: asyncpg.Record) -> Target:
    return Target(
        id=row["id"], name=row["name"], kind=row["kind"], url=row["url"], host=row["host"],
        port=row["port"], interval_s=row["interval_s"], timeout_s=float(row["timeout_s"]),
        expected_status=row["expected_status"], enabled=row["enabled"],
    )


class PgStore:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self.pool = pool

    @classmethod
    async def connect(cls, dsn: str, *, attempts: int = 30) -> "PgStore":
        """Connect, retrying while the database container is still starting."""
        import asyncio

        last: Exception | None = None
        for _ in range(attempts):
            try:
                pool = await asyncpg.create_pool(dsn, min_size=1, max_size=10)
                return cls(pool)
            except (OSError, asyncpg.PostgresError) as exc:
                last = exc
                await asyncio.sleep(1)
        raise RuntimeError(f"could not connect to PostgreSQL: {last}")

    async def close(self) -> None:
        await self.pool.close()

    async def migrate(self) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(SCHEMA)

    # ---- targets ---------------------------------------------------------

    async def list_targets(self) -> list[Target]:
        return [_target(r) for r in await self.pool.fetch(q.LIST_TARGETS)]

    async def target_rows(self) -> list[dict[str, Any]]:
        return [dict(r) for r in await self.pool.fetch(q.LIST_TARGETS)]

    async def get_target_row(self, target_id: int) -> dict[str, Any] | None:
        row = await self.pool.fetchrow(q.GET_TARGET, target_id)
        return dict(row) if row else None

    async def create_target(self, d: dict[str, Any]) -> tuple[Target, dict[str, Any]]:
        row = await self.pool.fetchrow(
            q.INSERT_TARGET, d["name"], d["kind"], d.get("url"), d.get("host"), d.get("port"),
            d["interval_s"], d["timeout_s"], d.get("expected_status"), d["enabled"],
        )
        return _target(row), dict(row)

    async def update_target(self, target_id: int, d: dict[str, Any]) -> tuple[Target, dict[str, Any]] | None:
        row = await self.pool.fetchrow(
            q.UPDATE_TARGET, target_id, d["name"], d["kind"], d.get("url"), d.get("host"),
            d.get("port"), d["interval_s"], d["timeout_s"], d.get("expected_status"), d["enabled"],
        )
        return (_target(row), dict(row)) if row else None

    async def delete_target(self, target_id: int) -> bool:
        status = await self.pool.execute(q.DELETE_TARGET, target_id)
        return status.endswith(" 1")

    async def count_targets(self) -> int:
        return await self.pool.fetchval(q.COUNT_TARGETS)

    # ---- results ---------------------------------------------------------

    async def insert_result(self, r: CheckResult) -> None:
        await self.pool.execute(
            q.INSERT_RESULT, r.target_id, r.checked_at, r.ok, r.latency_ms, r.status_code, r.error
        )

    async def latest_results(self) -> dict[int, dict[str, Any]]:
        return {r["target_id"]: dict(r) for r in await self.pool.fetch(q.LATEST_RESULTS)}

    async def recent_results(self, target_id: int, limit: int) -> list[dict[str, Any]]:
        return [dict(r) for r in await self.pool.fetch(q.RECENT_RESULTS, target_id, limit)]

    async def stats_all(self, since: datetime) -> dict[int, dict[str, Any]]:
        return {r["target_id"]: dict(r) for r in await self.pool.fetch(q.STATS_ALL, since)}

    async def stats_one(self, target_id: int, since: datetime) -> dict[str, Any]:
        return dict(await self.pool.fetchrow(q.STATS_ONE, target_id, since))

    async def history(self, target_id: int, since: datetime, bucket_s: int) -> list[dict[str, Any]]:
        rows = await self.pool.fetch(q.HISTORY, target_id, since, float(bucket_s))
        return [dict(r) for r in rows]

    async def prune(self, older_than: datetime) -> int:
        status = await self.pool.execute(q.PRUNE_RESULTS, older_than)
        return int(status.split()[-1])

    # ---- incidents -------------------------------------------------------

    async def open_incident(self, target_id: int, started_at: datetime, cause: str | None) -> int | None:
        return await self.pool.fetchval(q.OPEN_INCIDENT, target_id, started_at, cause)

    async def resolve_incident(self, target_id: int, resolved_at: datetime) -> int | None:
        return await self.pool.fetchval(q.RESOLVE_INCIDENT, target_id, resolved_at)

    async def open_incident_target_ids(self) -> list[int]:
        return [r["target_id"] for r in await self.pool.fetch(q.OPEN_INCIDENT_TARGETS)]

    async def list_incidents(
        self, target_id: int | None = None, open_only: bool = False, limit: int = 100
    ) -> list[dict[str, Any]]:
        rows = await self.pool.fetch(q.LIST_INCIDENTS, target_id, open_only, limit)
        return [dict(r) for r in rows]
