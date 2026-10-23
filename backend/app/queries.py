"""All SQL in one place. Parameters use asyncpg's $1, $2 ... placeholders."""

TARGET_COLUMNS = (
    "id, name, kind, url, host, port, interval_s, timeout_s, expected_status, enabled, created_at"
)

LIST_TARGETS = f"SELECT {TARGET_COLUMNS} FROM targets ORDER BY id"

GET_TARGET = f"SELECT {TARGET_COLUMNS} FROM targets WHERE id = $1"

INSERT_TARGET = f"""
INSERT INTO targets (name, kind, url, host, port, interval_s, timeout_s, expected_status, enabled)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
RETURNING {TARGET_COLUMNS}
"""

UPDATE_TARGET = f"""
UPDATE targets
SET name = $2, kind = $3, url = $4, host = $5, port = $6,
    interval_s = $7, timeout_s = $8, expected_status = $9, enabled = $10
WHERE id = $1
RETURNING {TARGET_COLUMNS}
"""

DELETE_TARGET = "DELETE FROM targets WHERE id = $1"

COUNT_TARGETS = "SELECT count(*) FROM targets"

INSERT_RESULT = """
INSERT INTO check_results (target_id, checked_at, ok, latency_ms, status_code, error)
VALUES ($1, $2, $3, $4, $5, $6)
"""

# ON CONFLICT relies on the partial unique index one_open_incident_per_target:
# if an incident is already open for this target, nothing is inserted and no id comes back.
OPEN_INCIDENT = """
INSERT INTO incidents (target_id, started_at, cause)
VALUES ($1, $2, $3)
ON CONFLICT (target_id) WHERE resolved_at IS NULL DO NOTHING
RETURNING id
"""

# GREATEST guards against a resolve time earlier than the start (clock skew).
RESOLVE_INCIDENT = """
UPDATE incidents
SET resolved_at = GREATEST($2, started_at)
WHERE target_id = $1 AND resolved_at IS NULL
RETURNING id
"""

OPEN_INCIDENT_TARGETS = "SELECT target_id FROM incidents WHERE resolved_at IS NULL"

LIST_INCIDENTS = """
SELECT i.id, i.target_id, t.name AS target_name, i.started_at, i.resolved_at, i.cause,
       EXTRACT(EPOCH FROM (COALESCE(i.resolved_at, now()) - i.started_at))::float8 AS duration_s
FROM incidents i
JOIN targets t ON t.id = i.target_id
WHERE ($1::bigint IS NULL OR i.target_id = $1)
  AND (NOT $2::boolean OR i.resolved_at IS NULL)
ORDER BY i.started_at DESC
LIMIT $3
"""

# Uptime and latency percentiles for every target since $1, in one pass.
# Latency is only taken from successful checks: a timeout isn't a latency.
STATS_ALL = """
SELECT target_id,
       count(*)                                    AS checks,
       count(*) FILTER (WHERE ok)                  AS ok_checks,
       avg(latency_ms) FILTER (WHERE ok)::float8   AS avg_ms,
       (percentile_cont(0.50) WITHIN GROUP (ORDER BY latency_ms) FILTER (WHERE ok))::float8 AS p50_ms,
       (percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms) FILTER (WHERE ok))::float8 AS p95_ms,
       (percentile_cont(0.99) WITHIN GROUP (ORDER BY latency_ms) FILTER (WHERE ok))::float8 AS p99_ms
FROM check_results
WHERE checked_at >= $1
GROUP BY target_id
"""

STATS_ONE = """
SELECT count(*)                                    AS checks,
       count(*) FILTER (WHERE ok)                  AS ok_checks,
       avg(latency_ms) FILTER (WHERE ok)::float8   AS avg_ms,
       (percentile_cont(0.50) WITHIN GROUP (ORDER BY latency_ms) FILTER (WHERE ok))::float8 AS p50_ms,
       (percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms) FILTER (WHERE ok))::float8 AS p95_ms,
       (percentile_cont(0.99) WITHIN GROUP (ORDER BY latency_ms) FILTER (WHERE ok))::float8 AS p99_ms
FROM check_results
WHERE target_id = $1 AND checked_at >= $2
"""

# Latest result per target. A LATERAL subquery does one "newest row for this
# target" lookup per target on the (target_id, checked_at DESC) index, so the
# cost depends on the number of targets, not on how many results are stored.
LATEST_RESULTS = """
SELECT t.id AS target_id, r.checked_at, r.ok, r.latency_ms, r.status_code, r.error
FROM targets t
CROSS JOIN LATERAL (
    SELECT checked_at, ok, latency_ms, status_code, error
    FROM check_results
    WHERE target_id = t.id
    ORDER BY checked_at DESC
    LIMIT 1
) r
"""

RECENT_RESULTS = """
SELECT checked_at, ok, latency_ms, status_code, error
FROM check_results
WHERE target_id = $1
ORDER BY checked_at DESC
LIMIT $2
"""

# Time-bucketed history for charts. date_bin (PostgreSQL 14+) rounds each
# timestamp down to the start of its $3-second bucket.
HISTORY = """
SELECT date_bin(make_interval(secs => $3), checked_at, TIMESTAMPTZ '2000-01-01 00:00:00+00') AS bucket,
       count(*)                                    AS checks,
       count(*) FILTER (WHERE ok)                  AS ok_checks,
       avg(latency_ms) FILTER (WHERE ok)::float8   AS avg_ms,
       (percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms) FILTER (WHERE ok))::float8 AS p95_ms
FROM check_results
WHERE target_id = $1 AND checked_at >= $2
GROUP BY bucket
ORDER BY bucket
"""

PRUNE_RESULTS = "DELETE FROM check_results WHERE checked_at < $1"
