from datetime import datetime, timedelta, timezone

import pytest

from app.detector import IncidentDetector
from app.models import CheckResult

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def feed(det: IncidentDetector, pattern: str, target_id: int = 1, start: int = 0):
    """Feed results like "ooxxx" (o = ok, x = fail), one per minute. Returns the events."""
    events = []
    for i, ch in enumerate(pattern):
        r = CheckResult(target_id, T0 + timedelta(minutes=start + i), ch == "o",
                        error=None if ch == "o" else f"fail {i}")
        ev = det.observe(r)
        if ev:
            events.append(ev)
    return events


def test_unknown_until_first_check():
    det = IncidentDetector()
    assert det.status(1) == "unknown"
    feed(det, "o")
    assert det.status(1) == "up"


def test_single_failure_does_not_open_incident():
    det = IncidentDetector(failure_threshold=3)
    assert feed(det, "ooxoo") == []
    assert det.status(1) == "up"


def test_failures_below_threshold_show_degraded():
    det = IncidentDetector(failure_threshold=3)
    feed(det, "oxx")
    assert det.status(1) == "degraded"


def test_opens_after_threshold_with_start_time_of_first_failure():
    det = IncidentDetector(failure_threshold=3)
    events = feed(det, "ooxxx")
    assert len(events) == 1
    ev = events[0]
    assert ev.kind == "opened"
    assert ev.at == T0 + timedelta(minutes=2)          # first failure, the real start
    assert ev.detected_at == T0 + timedelta(minutes=4)  # when the threshold was reached
    assert ev.cause == "fail 4"
    assert det.status(1) == "down"


def test_does_not_alert_twice_for_one_outage():
    det = IncidentDetector(failure_threshold=2)
    events = feed(det, "xxxxxxxx")
    assert [e.kind for e in events] == ["opened"]


def test_recovery_needs_consecutive_successes():
    det = IncidentDetector(failure_threshold=2, recovery_threshold=2)
    events = feed(det, "xx" + "oxoxox")  # flapping: never two oks in a row
    assert [e.kind for e in events] == ["opened"]
    assert det.status(1) == "down"
    events = feed(det, "oo", start=10)
    assert [e.kind for e in events] == ["resolved"]
    assert events[0].at == T0 + timedelta(minutes=10)  # first ok of the recovery streak
    assert det.status(1) == "up"


def test_full_cycle_open_resolve_open():
    det = IncidentDetector(failure_threshold=2, recovery_threshold=1)
    events = feed(det, "xxoxx")
    assert [e.kind for e in events] == ["opened", "resolved", "opened"]


def test_targets_are_independent():
    det = IncidentDetector(failure_threshold=2)
    feed(det, "xx", target_id=1)
    feed(det, "oo", target_id=2)
    assert det.status(1) == "down"
    assert det.status(2) == "up"


def test_restore_down_after_restart_prevents_duplicate_alert():
    det = IncidentDetector(failure_threshold=2, recovery_threshold=1)
    det.restore_down(7)
    assert det.status(7) == "down"
    assert feed(det, "xxx", target_id=7) == []           # already down: no new incident
    assert [e.kind for e in feed(det, "o", target_id=7)] == ["resolved"]


def test_forget_resets_state():
    det = IncidentDetector(failure_threshold=1)
    feed(det, "x")
    det.forget(1)
    assert det.status(1) == "unknown"


def test_invalid_thresholds_rejected():
    with pytest.raises(ValueError):
        IncidentDetector(failure_threshold=0)
