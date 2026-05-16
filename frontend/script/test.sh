#!/usr/bin/env bash
# Frontend Worker smoke test. It expects the backend Worker to be reachable.
#
# Usage:
#   bash frontend/script/test.sh local
#   bash frontend/script/test.sh cloud https://paper-sniffer-frontend.<subdomain>.workers.dev

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SRC_VARS="$ROOT/frontend/script/config/.dev.vars"

MODE="${1:-local}"
[[ "$MODE" =~ ^(local|cloud)$ ]] || {
  echo "Usage: bash frontend/script/test.sh [local|cloud] [base_url]" >&2
  exit 1
}

if [[ -f "$SRC_VARS" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$SRC_VARS"
  set +a
fi

case "$MODE" in
  local)
    BASE_URL="${2:-${BASE_URL:-http://127.0.0.1:8788}}"
    ;;
  cloud)
    BASE_URL="${2:-${BASE_URL:-}}"
    if [[ -z "$BASE_URL" ]]; then
      echo "Error: cloud tests need a base URL argument or BASE_URL." >&2
      exit 1
    fi
    ;;
esac

BASE_URL="${BASE_URL%/}"
COOKIE_JAR="$(mktemp)"
cleanup() {
  rm -f "$COOKIE_JAR"
}
trap cleanup EXIT

curl_common=(--silent --show-error --connect-timeout 15 --max-time 30)

if [[ -n "${FRONTEND_PASSWORD:-}" ]]; then
  echo "==> Logging in to frontend"
  status="$(
    curl "${curl_common[@]}" \
      --request POST \
      --cookie-jar "$COOKIE_JAR" \
      --output /tmp/paper-sniffer-login.out \
      --write-out "%{http_code}" \
      --data-urlencode "password=$FRONTEND_PASSWORD" \
      "$BASE_URL/login"
  )"
  [[ "$status" == "303" ]] || {
    echo "FAIL login expected 303, got $status" >&2
    cat /tmp/paper-sniffer-login.out >&2 || true
    exit 1
  }
fi

request() {
  local path="$1"
  local expected="$2"
  local output
  output="$(mktemp)"
  local status
  status="$(
    curl "${curl_common[@]}" \
      --cookie "$COOKIE_JAR" \
      --output "$output" \
      --write-out "%{http_code}" \
      "$BASE_URL$path"
  )"
  if [[ "$status" != "$expected" ]]; then
    echo "FAIL $path expected $expected, got $status" >&2
    sed 's/^/  /' "$output" >&2
    rm -f "$output"
    exit 1
  fi
  rm -f "$output"
  echo "PASS $path -> $status"
}

request /status 200
request /api/health 200

echo "==> Frontend smoke tests passed"
