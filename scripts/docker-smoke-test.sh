#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

SMOKE_TEST_TIMEOUT="${SMOKE_TEST_TIMEOUT:-120}"
SMOKE_TEST_INTERVAL="${SMOKE_TEST_INTERVAL:-2}"

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

show_failure_details() {
  echo "--- docker compose ps ---" >&2
  if ! docker compose ps >&2; then
    echo "docker compose ps failed" >&2
  fi
  echo "--- api logs ---" >&2
  if ! docker compose logs --no-color api >&2; then
    echo "api logs unavailable" >&2
  fi
  echo "--- postgres logs ---" >&2
  if ! docker compose logs --no-color postgres >&2; then
    echo "postgres logs unavailable" >&2
  fi
  echo "--- redis logs ---" >&2
  if ! docker compose logs --no-color redis >&2; then
    echo "redis logs unavailable" >&2
  fi
}

fail_with_context() {
  echo "$1" >&2
  show_failure_details
  exit 1
}

require_command docker
require_command curl
require_command python3

if ! docker info >/dev/null 2>&1; then
  echo "Docker daemon is not reachable." >&2
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "Docker Compose is not available through 'docker compose'." >&2
  exit 1
fi

if [ ! -f .env ]; then
  cp .env.example .env
fi

# shellcheck disable=SC1091
set -a
source .env
set +a

API_PORT="${API_PORT:-8000}"
POSTGRES_USER="${POSTGRES_USER:-resource_monitoring}"
POSTGRES_DB="${POSTGRES_DB:-resource_monitoring}"

if ! docker compose config >/dev/null; then
  fail_with_context "docker compose config failed."
fi

if ! docker compose build; then
  fail_with_context "docker compose build failed."
fi

cleanup() {
  echo "Stopping Docker Compose services..."
  docker compose down >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

if ! docker compose up -d; then
  fail_with_context "docker compose up -d failed."
fi

wait_for_service_health() {
  local service_name="$1"
  local deadline=$((SECONDS + SMOKE_TEST_TIMEOUT))
  local output
  local state
  local health

  while (( SECONDS < deadline )); do
    output="$(docker compose ps --format json 2>/dev/null || true)"
    if [ -n "$output" ]; then
      state="$(python3 - "$service_name" "$output" <<'PY'
import json
import sys
service_name = sys.argv[1]
raw = sys.argv[2]
try:
    rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
except json.JSONDecodeError:
    sys.exit(0)
for row in rows:
    if row.get("Service") == service_name:
        print(row.get("State", ""))
        print(row.get("Health", ""))
        break
else:
    print("")
    print("")
PY
)"
      if [ -n "$state" ]; then
        health="$(printf '%s\n' "$state" | tail -n 1)"
        state="$(printf '%s\n' "$state" | head -n 1)"
        if [ "$health" = "healthy" ]; then
          return 0
        fi
        if [ "$state" = "exited" ] || [ "$state" = "dead" ]; then
          fail_with_context "Service $service_name ended unexpectedly."
        fi
      fi
    fi
    sleep "$SMOKE_TEST_INTERVAL"
  done

  fail_with_context "Timed out waiting for $service_name to become healthy."
}

wait_for_service_health api
wait_for_service_health postgres
wait_for_service_health redis

root_response="$(curl --fail --silent --show-error "http://localhost:${API_PORT}/")"
health_response="$(curl --fail --silent --show-error "http://localhost:${API_PORT}/health")"

python3 - "$root_response" <<'PY'
import json
import sys
payload = json.loads(sys.argv[1])
assert payload.get("service") == "resource-monitoring-api", payload
assert payload.get("status") == "running", payload
PY

python3 - "$health_response" <<'PY'
import json
import sys
payload = json.loads(sys.argv[1])
assert payload.get("status") == "healthy", payload
PY

docker compose exec -T postgres pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"

redis_response="$(docker compose exec -T redis redis-cli ping)"
redis_normalized="$(printf '%s' "$redis_response" | tr -d '[:space:]')"
if [ "$redis_normalized" != "PONG" ]; then
  fail_with_context "Redis did not return PONG."
fi

echo "Smoke test passed: API, PostgreSQL, and Redis are healthy."
