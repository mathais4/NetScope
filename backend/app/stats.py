"""Small helpers for turning raw counts into the numbers shown on the dashboard."""

from __future__ import annotations


def uptime_pct(ok_checks: int, checks: int) -> float | None:
    """Share of checks that succeeded, as a percentage rounded to 3 dp.

    Returns None (shown as "no data") when there were no checks, rather than
    claiming 0% or 100% uptime for a target nobody has looked at yet.
    """
    if checks <= 0:
        return None
    return round(100.0 * ok_checks / checks, 3)
