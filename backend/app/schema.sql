-- NetScope schema. Applied at startup; every statement is idempotent.

CREATE TABLE IF NOT EXISTS targets (
    id              BIGSERIAL PRIMARY KEY,
    name            TEXT        NOT NULL CHECK (length(name) BETWEEN 1 AND 100),
    kind            TEXT        NOT NULL CHECK (kind IN ('http', 'tcp', 'ping')),
    url             TEXT,
    host            TEXT,
    port            INTEGER     CHECK (port BETWEEN 1 AND 65535),
    interval_s      INTEGER     NOT NULL DEFAULT 30 CHECK (interval_s BETWEEN 5 AND 3600),
    timeout_s       REAL        NOT NULL DEFAULT 5 CHECK (timeout_s > 0 AND timeout_s <= 30),
    expected_status INTEGER     CHECK (expected_status BETWEEN 100 AND 599),
    enabled         BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- each kind of check needs its own address fields
    CONSTRAINT target_address CHECK (
        (kind = 'http' AND url IS NOT NULL) OR
        (kind = 'tcp'  AND host IS NOT NULL AND port IS NOT NULL) OR
        (kind = 'ping' AND host IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS check_results (
    id          BIGSERIAL PRIMARY KEY,
    target_id   BIGINT      NOT NULL REFERENCES targets (id) ON DELETE CASCADE,
    checked_at  TIMESTAMPTZ NOT NULL,
    ok          BOOLEAN     NOT NULL,
    latency_ms  REAL,
    status_code INTEGER,
    error       TEXT
);

-- Almost every read is "results for one target over a time window, newest first".
CREATE INDEX IF NOT EXISTS check_results_target_time
    ON check_results (target_id, checked_at DESC);
-- Used by the retention job, which deletes by age across all targets.
CREATE INDEX IF NOT EXISTS check_results_time
    ON check_results (checked_at);

CREATE TABLE IF NOT EXISTS incidents (
    id          BIGSERIAL PRIMARY KEY,
    target_id   BIGINT      NOT NULL REFERENCES targets (id) ON DELETE CASCADE,
    started_at  TIMESTAMPTZ NOT NULL,
    resolved_at TIMESTAMPTZ,
    cause       TEXT,
    CHECK (resolved_at IS NULL OR resolved_at >= started_at)
);

-- The database itself guarantees at most one open incident per target,
-- so a bug or a restart can never produce duplicate outages.
CREATE UNIQUE INDEX IF NOT EXISTS one_open_incident_per_target
    ON incidents (target_id) WHERE resolved_at IS NULL;

CREATE INDEX IF NOT EXISTS incidents_started
    ON incidents (started_at DESC);
