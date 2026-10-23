# NetScope design notes

Why NetScope is built the way it is, what the alternatives were, and where it falls short. Read this before talking about the project in an interview.

## The 30-second version

> NetScope is a monitoring service. You give it websites, server ports and devices; a background scheduler checks each one on its own interval using HTTP, TCP or ping, and stores every result in PostgreSQL. It turns those results into uptime and latency percentiles, detects outages with a threshold so one blip doesn't cause an alert, and pushes everything live to a React dashboard over a WebSocket. It all runs with one `docker compose up`, including a demo service I can break on purpose to show an outage being detected and resolved.

## Life of one check

1. **`Monitor.tick()`** runs every second. For each enabled target, it checks two things: is the target due (`next_due <= now`), and is it not already being checked (`id not in _in_flight`)? If both are true, it sets `next_due = now + interval` and starts `_run(target)` as its own asyncio task.
2. **`_run`** waits on a semaphore (at most 50 checks at once), then calls `run_check`. That dispatches to `check_http`, `check_tcp` or `check_ping`, which returns an `Outcome`: ok, latency, status code and error. A probe never raises, because "unreachable" is a normal result.
3. The result is **inserted** into `check_results`.
4. **`IncidentDetector.observe(result)`** updates that target's counters and may return an `opened` or `resolved` event.
5. **`Notifier`** pushes the result to every WebSocket client. On an event, it also writes the incident to PostgreSQL, logs it and posts the webhook.
6. The dashboard receives the WebSocket message and updates that row's status, last latency and sparkline without reloading.

## Decisions and alternatives

### asyncio rather than threads, Celery or cron
Checks spend nearly all their time waiting on the network. asyncio can have hundreds waiting at once on a single thread, with no locks. A thread per check would work but uses far more memory and needs care around shared state. Celery would need Redis or RabbitMQ and a separate worker process, which is overkill for one service. Cron can't run at sub-minute intervals or on a per-target schedule.

### No overlapping checks for one target
If a target hangs until its timeout, the next tick must not start a second check on top of it. Otherwise a slow target would pile up checks and use up the concurrency limit. The `_in_flight` set prevents this. `test_slow_check_is_not_started_twice` covers it.

### `next_due` is set when a check starts, not when it finishes
Setting it at the start keeps the schedule fixed: a 10-second interval means a check every 10 seconds. Setting it after the check finishes would make the schedule drift later by however long each check took.

### Semaphore for concurrency
With 500 targets all due at once, it caps open sockets and subprocesses at 50. The rest wait their turn instead of overloading the host or the network.

### Ping by running the `ping` binary
Sending ICMP yourself needs a raw socket, which requires root or `CAP_NET_RAW`. The system `ping` already has that permission, so NetScope runs it and parses `time=12.3 ms` from its output. The trade-off is one process per ping, which is fine at these numbers. The Docker image installs `iputils-ping`.

### Hysteresis: 3 failures to go down, 2 successes to come up
Networks lose the odd packet. Alerting on a single failure would make alerts noise, and people learn to ignore noisy alerts. Requiring two successes before recovery stops a service that alternates pass/fail from opening and closing incidents on every check. The cost is detection delay: with a 10-second interval, an outage is confirmed about 20–30 seconds after it starts. The thresholds are configurable.

The dashboard has a fourth state, **Degraded**: failing, but not for long enough yet. It tells you something is wrong without raising an alert.

### An incident starts at the first failed check
The detector remembers when the failing streak began. Using the time the threshold was crossed would understate every outage by about two intervals. Likewise, recovery is timed at the first good check of the recovery streak.

### Latency statistics come only from successful checks
A timeout is not a 5-second response; it's a failure. Counting it as latency would hide outages inside the latency chart. So uptime and latency are reported separately.

### Percentiles rather than averages
One 3-second response among 99 fast ones barely moves the average, but users notice it. p95 means "95% of checks were faster than this", and p99 shows the slow tail. PostgreSQL computes them with `percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms)`, so the raw rows never have to come back to Python.

### Plain SQL with asyncpg, no ORM
The interesting work here is queries: percentiles, time buckets, latest-row-per-group. Writing them as SQL keeps them readable and easy to `EXPLAIN`. Every query is in `queries.py`.

### Indexes and query shapes
- `check_results (target_id, checked_at DESC)`: almost every read is one target's results in a time window, newest first.
- The latest result per target uses a `LATERAL` subquery with `ORDER BY checked_at DESC LIMIT 1`. That's one index lookup per target, so it stays fast however many results are stored. (A simpler `DISTINCT ON` version reads the whole table, which becomes slow once there are millions of rows.)
- `date_bin(interval, checked_at, origin)` rounds each timestamp into fixed buckets (1 minute, 15 minutes or 2 hours) for the charts.
- `check_results (checked_at)` supports the retention job, which deletes by age across all targets.

### The database enforces "one open incident per target"
```sql
CREATE UNIQUE INDEX one_open_incident_per_target ON incidents (target_id) WHERE resolved_at IS NULL;
```
This is a partial unique index: it only applies to rows that aren't resolved yet. Even if the code had a bug, or two processes raced, the database would refuse a second open incident. The insert uses `ON CONFLICT ... DO NOTHING`, so the duplicate attempt is simply ignored.

### Restarts
At startup, the monitor loads targets plus any open incidents and marks those targets as down. So a restart during an outage doesn't send a second "DOWN" alert, and recovery is still detected. Other targets show as Pending until their first check, a few seconds later.

### WebSocket fan-out with bounded queues
Each dashboard connection gets its own queue of up to 200 messages. If a browser can't keep up (a slow network, or a sleeping laptop), its messages are dropped. The monitor never waits for a browser. The client reconnects with exponential backoff (1 s, 2 s, 4 s … up to 15 s).

### Failures inside NetScope don't stop monitoring
A database outage, a broken webhook or a bug in a checker is logged, and the loop carries on. Tests cover each case (`test_database_error_does_not_stop_monitoring`, `test_crashing_checker_is_recorded_as_failure`). A monitoring tool that dies when something breaks is useless.

### Hand-drawn SVG charts
The charts are about 150 lines of React and SVG, with no charting library. There's one less dependency, and every axis and line can be explained.

## Known limitations (and what I'd do next)

- **Single instance.** The scheduler runs inside the API process, so two replicas would check everything twice. Fix: elect one scheduler with a PostgreSQL advisory lock (`pg_try_advisory_lock`), or split the scheduler into its own service.
- **One vantage point.** If NetScope's own network fails, everything looks down. Real monitoring checks from several locations and only alerts when most agree.
- **Raw results grow without limit, up to retention.** 100 targets checked every 10 seconds is about 860,000 rows a day. Next steps: roll up old data into per-minute or per-hour summaries, and partition `check_results` by day (dropping a partition is much cheaper than `DELETE`), or use TimescaleDB.
- **No authentication.** Anyone who can reach the dashboard can add or delete targets. It would need login, and should not be exposed to the internet as it is.
- **Webhook alerts aren't retried.** A failed delivery is only logged. A retry queue with backoff would fix that.
- **SSRF risk if made multi-user.** Users can make the server request any URL, including internal ones. A public version would need an allow-list.

## Questions you'll probably be asked

**Why not just alert on the first failure?** Packet loss and brief blips are normal. Alerts that are usually false get ignored. The threshold trades about 20 seconds of detection delay for alerts people trust.

**How do you know the outage duration is accurate?** The incident start is the timestamp of the first failed check in the streak, and the end is the first successful check. Duration error is at most one check interval.

**What happens if a target takes 30 seconds to time out but the interval is 10 seconds?** That can't be configured: validation requires the timeout to be shorter than the interval. Even if it could, the `_in_flight` guard means a second check never starts while the first is still running.

**How would this scale to 10,000 targets?** First, the concurrency cap and database writes become the limits. I'd batch inserts (`COPY` or multi-row `INSERT`), raise the cap, and run several scheduler workers that each own a shard of targets (`target_id % N`). For storage, I'd partition by time and roll up old data.

**Why PostgreSQL rather than a time-series database?** It was already needed for targets and incidents. `percentile_cont` and `date_bin` cover the time-series queries at this scale, so one database is simpler to run. Past a few million rows a day, I'd look at TimescaleDB, which is still PostgreSQL.

**How do you test something that depends on time and the network?** I separated the logic from the I/O. The detector is pure. The scheduler takes an injectable clock, checker and store, so tests move time forward by hand and script outcomes like "ok, ok, fail, fail, fail". The probes are tested against real sockets on localhost, including a server that deliberately responds too slowly.

**What's the difference between your TCP and HTTP checks?** TCP only proves a process is accepting connections on that port. HTTP proves the application actually answered, and with the expected status. A web server can accept TCP connections and still return 500 for every request.

**Why does ping need special treatment in Docker?** ICMP needs a raw socket. Docker grants `NET_RAW` by default, and the `ping` binary is installed in the image. Some hardened hosts drop that capability, and then ping checks fail with a clear error rather than crashing.

## Make it yours

The best way to own this project is to extend it. Each of these is a good afternoon, and each gives you a story to tell:

1. **TLS certificate expiry check.** Connect with `ssl`, read the certificate's `notAfter`, and warn when it's under 14 days away.
2. **DNS check.** Resolve a name and alert if the answer changes or resolution fails.
3. **Maintenance windows.** Pause alerts, but keep recording, during planned work.
4. **Advisory-lock leader election,** so two API replicas don't double-check.
5. **Measure it.** Add 200 targets pointing at the demo service. Record checks per second, p95 check scheduling delay and database size per day, then put the real numbers on your CV.
