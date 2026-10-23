#!/usr/bin/env sh
# Switch the demo service's behaviour and watch NetScope react.
#   ./scripts/chaos.sh down    # returns 503: an incident opens after 3 failed checks (~30 s)
#   ./scripts/chaos.sh slow    # 1.5-3 s responses: watch p95 climb on the chart
#   ./scripts/chaos.sh flaky   # ~40% errors: status flips to Degraded, rarely a full outage
#   ./scripts/chaos.sh up      # back to normal: incident resolves after 2 good checks
set -e
MODE="${1:-}"
case "$MODE" in
  up|down|slow|flaky) curl -fsS -X POST "http://localhost:8081/mode/$MODE"; echo ;;
  *) echo "usage: $0 up|down|slow|flaky" >&2; exit 1 ;;
esac
