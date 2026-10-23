"""Demo targets created on first start when SEED_DEMO=true (see docker-compose.yml).

They point at the other containers in the stack, so the dashboard has something
real to show straight away, including a service you can break on purpose.
"""

import os
from urllib.parse import urlsplit

DEMO_TARGETS = [
    {"name": "Demo web service", "kind": "http", "url": "http://flaky:8080/health", "interval_s": 10, "timeout_s": 3},
    {"name": "NetScope API", "kind": "http", "url": "http://localhost:8000/api/health", "interval_s": 15, "timeout_s": 3},
    {"name": "PostgreSQL", "kind": "tcp", "host": "db", "port": 5432, "interval_s": 15, "timeout_s": 3},
    {"name": "Database host (ping)", "kind": "ping", "host": "db", "interval_s": 15, "timeout_s": 2},
    {"name": "Cloudflare DNS", "kind": "ping", "host": "1.1.1.1", "interval_s": 30, "timeout_s": 2},
    {"name": "example.com", "kind": "http", "url": "https://example.com", "interval_s": 60, "timeout_s": 5},
]


def demo_targets(database_url: str) -> list[dict]:
    if os.getenv("SEED_PROFILE") != "cloud":
        return DEMO_TARGETS
    port = int(os.getenv("PORT", "10000"))
    db = urlsplit(database_url)
    return [
        {"name": "NetScope API", "kind": "http", "url": f"http://127.0.0.1:{port}/api/health", "interval_s": 30, "timeout_s": 5},
        {"name": "Example website", "kind": "http", "url": "https://example.com", "interval_s": 60, "timeout_s": 10},
        {"name": "Cloudflare website", "kind": "http", "url": "https://www.cloudflare.com", "interval_s": 60, "timeout_s": 10},
        {"name": "PostgreSQL port", "kind": "tcp", "host": db.hostname, "port": db.port or 5432, "interval_s": 30, "timeout_s": 5},
        {"name": "Intentional failure demo (closed local port)", "kind": "tcp", "host": "127.0.0.1", "port": 1, "interval_s": 30, "timeout_s": 2},
    ]
