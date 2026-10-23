# NetScope

**For a lasting public live link, follow [DEPLOY_RENDER.md](DEPLOY_RENDER.md).**
The root Dockerfile and render.yaml deploy the app and PostgreSQL on Render.
This hosting configuration uses paid resources; review the charges before deploying.

**Network and service monitoring dashboard.** NetScope checks websites, server ports and devices on a schedule (HTTP, TCP and ping), records every result in PostgreSQL, works out uptime and latency percentiles, detects outages, sends alerts, and shows it all on a live dashboard.

Python · FastAPI · asyncio · PostgreSQL · React · TypeScript · Docker

![Overview](docs/screenshots/overview.png)

| Target detail | Incidents |
|---|---|
| ![Detail](docs/screenshots/detail.png) | ![Incidents](docs/screenshots/incidents.png) |

## Features

- **Three check types.** HTTP (status code and response time), TCP connect (is the port open?), ICMP ping (is the device reachable?).
- **Background scheduler.** Each target is checked on its own interval. Checks run concurrently with asyncio, capped by a semaphore, and a slow target never gets a second check stacked on top of the first.
- **Outage detection with hysteresis.** A target is only declared down after 3 failed checks in a row, and only back up after 2 successes in a row. One dropped packet doesn't page anyone, and a flapping service doesn't open a new incident every 10 seconds.
- **Accurate incident times.** An incident starts at the *first* failed check, not when the threshold was reached, so reported downtime matches reality.
- **Alerts.** Live toast notifications on the dashboard, log lines, and an optional webhook (Slack and Discord compatible).
- **Statistics in SQL.** Uptime, average, p50/p95/p99 latency, and time-bucketed history for the charts, all computed by PostgreSQL (`percentile_cont`, `date_bin`).
- **Live dashboard.** Results stream over a WebSocket. The client reconnects with exponential backoff if the API restarts.
- **Survives restarts.** Open incidents are reloaded at startup, and a partial unique index guarantees at most one open incident per target.
- **Retention.** Results older than 30 days (configurable) are deleted hourly.
- **Chaos demo.** A deliberately breakable service is included, so you can cause an outage and watch NetScope catch it.

## Quick start

```bash
docker compose up --build
```

Open **http://localhost:8080**. Six demo targets are created on first start: the demo web service, the API itself, PostgreSQL (TCP and ping), Cloudflare DNS and example.com.

### Break something

```bash
./scripts/chaos.sh down    # demo service returns 503 -> incident opens after ~30 s (3 checks x 10 s)
./scripts/chaos.sh up      # recovers -> incident resolves after 2 good checks
./scripts/chaos.sh slow    # 1.5-3 s responses -> watch p95 climb on the chart
./scripts/chaos.sh flaky   # ~40% errors -> status shows Degraded
```

Or stop the database and watch the TCP and ping targets go down: `docker compose stop db`. The API keeps running, logs the failed writes and recovers when the database is back.

### Alerts to Slack or Discord

Create an incoming webhook, then:

```bash
ALERT_WEBHOOK_URL=https://hooks.slack.com/services/... docker compose up
```

## Architecture

```mermaid
flowchart LR
    subgraph api [FastAPI process]
        M[Monitor<br/>asyncio scheduler] -->|run_check| C[Checks<br/>HTTP · TCP · ping]
        M --> D[IncidentDetector<br/>3 fails down / 2 oks up]
        M --> N[Notifier]
        R[REST API] --> S[(PgStore<br/>asyncpg)]
        M --> S
        N --> H[WebSocket hub]
        N --> W[Webhook]
    end
    C -->|probe| T[Targets on the network]
    S --> PG[(PostgreSQL)]
    B[React dashboard] -->|/api| R
    H -->|/ws live updates| B
```

The monitoring logic (`checks.py`, `detector.py`, `scheduler.py`) has no web or database code in it. The scheduler talks to storage through a small `MonitorStore` interface, so tests swap in an in-memory store and drive time by hand.

See [docs/DESIGN.md](docs/DESIGN.md) for the reasoning behind each design choice.

## API

| Method | Path | Description |
|---|---|---|
| GET | `/api/health` | Liveness check |
| GET | `/api/summary` | Counts by status, open incidents, overall 24 h uptime |
| GET | `/api/targets` | All targets with status, last result and 24 h stats |
| POST | `/api/targets` | Add a target (validated: HTTP needs a URL, TCP a host and port, ping a host) |
| GET / PUT / DELETE | `/api/targets/{id}` | Read, replace or delete a target |
| POST | `/api/targets/{id}/check` | Run a check immediately |
| GET | `/api/targets/{id}/results?limit=50` | Latest raw results |
| GET | `/api/targets/{id}/history?range=1h\|24h\|7d` | Bucketed uptime and latency for charts |
| GET | `/api/incidents?open_only=&target_id=` | Incident log |
| WS | `/ws` | Live stream of check results and incident events |

FastAPI's interactive API docs are at http://localhost:8080/docs.

## Running locally without Docker

```bash
# database
docker compose up -d db

# backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
DATABASE_URL=postgresql://netscope:netscope@localhost:5434/netscope SEED_DEMO=true uvicorn app.main:app --reload

# frontend (new terminal)
cd frontend
npm install
npm run dev        # http://localhost:5173, proxies /api and /ws to :8000
```

## Tests

```bash
cd backend
pytest                                   # unit tests: probes, detector, scheduler, validation
TEST_DATABASE_URL=postgresql://netscope:netscope@localhost:5434/netscope pytest   # + API tests on real PostgreSQL
```

- `test_checks.py` runs real probes against sockets on localhost: a tiny HTTP server, an open port and a closed one. It covers timeouts, refused connections, unexpected status codes and DNS failures.
- `test_detector.py` covers threshold behaviour, flapping, recovery, restart and per-target isolation.
- `test_scheduler.py` uses a fake clock and a scripted checker to test the scheduler. It checks intervals, no overlapping checks, the concurrency cap, the full outage → alert → recovery cycle, no re-alerting after a restart, and that the loop keeps running through database errors and checker crashes.
- `test_api.py` runs end to end through FastAPI against PostgreSQL.

CI (GitHub Actions) runs all of it against a PostgreSQL service container and builds the frontend.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | `postgresql://netscope:netscope@localhost:5432/netscope` | PostgreSQL connection |
| `FAILURE_THRESHOLD` | `3` | Consecutive failures before a target is down |
| `RECOVERY_THRESHOLD` | `2` | Consecutive successes before it is up again |
| `MAX_CONCURRENT_CHECKS` | `50` | Cap on simultaneous probes |
| `RETENTION_DAYS` | `30` | How long raw results are kept |
| `ALERT_WEBHOOK_URL` | — | Slack/Discord-compatible webhook for incident alerts |
| `SEED_DEMO` | `false` | Create demo targets when the database is empty |

## Project layout

```
backend/app/
  checks.py      HTTP, TCP and ping probes
  detector.py    outage detection (hysteresis state machine)
  scheduler.py   background monitor loop
  notifier.py    WebSocket hub, logging, webhook alerts
  store.py       PostgreSQL access (asyncpg)
  queries.py     every SQL query
  schema.sql     tables, constraints, indexes
  main.py        FastAPI app and routes
frontend/src/
  App.tsx        routing, live feed, global state
  pages/         Overview, TargetDetail, Incidents
  components/    hand-written SVG charts, form, status pills
demo/flaky/      breakable demo service
```
