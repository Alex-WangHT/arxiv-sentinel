#!/usr/bin/env bash
# API smoke tests for local or Cloudflare Worker deployments.
#
# Usage:
#   bash backend/script/test.sh local
#   bash backend/script/test.sh cloud https://paper-sniffer-backend.<your-subdomain>.workers.dev
#
# You can also set BASE_URL/PAPER_SNIFFER_BASE_URL for cloud tests.
# ADMIN_TOKEN is read from the environment or backend/script/config/.dev.vars.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SRC_VARS="$ROOT/backend/script/config/.dev.vars"

usage() {
  local exit_code="${1:-1}"
  cat >&2 <<'EOF'
Usage:
  bash backend/script/test.sh [local|cloud] [base_url]

Examples:
  bash backend/script/test.sh local
  bash backend/script/test.sh cloud https://paper-sniffer-backend.<your-subdomain>.workers.dev
  BASE_URL=https://paper-sniffer-backend.<your-subdomain>.workers.dev bash backend/script/test.sh cloud

Environment knobs:
  CONNECT_TIMEOUT=30
  CURL_MAX_TIME=30
  RUN_TRIGGER_MAX_TIME=30
  POLL_INTERVAL=10
  POLL_TIMEOUT=900
  SHOW_RESPONSE=true
EOF
  exit "$exit_code"
}

MODE="${1:-local}"
if [[ "$MODE" == "-h" || "$MODE" == "--help" ]]; then
  usage 0
fi
[[ "$MODE" =~ ^(local|cloud)$ ]] || usage

cd "$ROOT"

if [[ -f "$SRC_VARS" ]]; then
  # shellcheck disable=SC1090
  set -a
  source "$SRC_VARS"
  set +a
elif [[ -z "${ADMIN_TOKEN:-}" ]]; then
  echo "Error: missing ADMIN_TOKEN. Create $SRC_VARS or export ADMIN_TOKEN." >&2
  exit 1
fi

if [[ -z "${ADMIN_TOKEN:-}" ]]; then
  echo "Error: ADMIN_TOKEN is empty." >&2
  exit 1
fi

case "$MODE" in
  local)
    BASE_URL="${2:-${BASE_URL:-${PAPER_SNIFFER_BASE_URL:-http://127.0.0.1:8787}}}"
    ;;
  cloud)
    BASE_URL="${2:-${BASE_URL:-${PAPER_SNIFFER_BASE_URL:-}}}"
    if [[ -z "$BASE_URL" ]]; then
      echo "Error: cloud tests need a base URL argument or BASE_URL/PAPER_SNIFFER_BASE_URL." >&2
      usage
    fi
    ;;
esac

BASE_URL="${BASE_URL%/}"
TEST_DATE="${TEST_DATE:-2026-05-12}"
CONNECT_TIMEOUT="${CONNECT_TIMEOUT:-30}"
CURL_MAX_TIME="${CURL_MAX_TIME:-30}"
RUN_TRIGGER_MAX_TIME="${RUN_TRIGGER_MAX_TIME:-30}"
POLL_INTERVAL="${POLL_INTERVAL:-10}"
POLL_TIMEOUT="${POLL_TIMEOUT:-900}"
SHOW_RESPONSE="${SHOW_RESPONSE:-true}"
AUTH_HEADER="Authorization: Bearer $ADMIN_TOKEN"

if ! command -v curl >/dev/null 2>&1; then
  echo "Error: curl is required to run API tests." >&2
  exit 1
fi

TMP_DIR="$(mktemp -d)"
cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

PASS_COUNT=0

print_response() {
  local body_file="$1"

  if [[ "$SHOW_RESPONSE" != "true" ]]; then
    return
  fi

  echo "Response body:"
  if [[ -s "$body_file" ]]; then
    sed 's/^/  /' "$body_file"
  else
    echo "  <empty>"
  fi
}

fail_with_response() {
  local message="$1"
  local body_file="$2"

  echo "FAIL $message" >&2
  echo "Response body:" >&2
  if [[ -s "$body_file" ]]; then
    sed 's/^/  /' "$body_file" >&2
  else
    echo "  <empty>" >&2
  fi
  exit 1
}

request() {
  local method="$1"
  local path="$2"
  local expected_status="$3"
  local name="$4"
  local body="${5:-}"
  local auth="${6:-yes}"
  local max_time="${7:-$CURL_MAX_TIME}"
  local body_file="$TMP_DIR/response_${PASS_COUNT}.json"
  local error_file="$TMP_DIR/curl_error_${PASS_COUNT}.txt"
  local status
  local curl_exit
  local args=(
    --silent
    --show-error
    --connect-timeout "$CONNECT_TIMEOUT"
    --max-time "$max_time"
    --request "$method"
    --output "$body_file"
    --write-out "%{http_code}"
  )

  if [[ "$auth" == "yes" ]]; then
    args+=(--header "$AUTH_HEADER")
  fi

  if [[ -n "$body" ]]; then
    args+=(--header "Content-Type: application/json" --data "$body")
  fi

  set +e
  status="$(curl "${args[@]}" "$BASE_URL$path" 2>"$error_file")"
  curl_exit=$?
  set -e

  if (( curl_exit != 0 )); then
    echo "FAIL $name: curl failed with exit code $curl_exit" >&2
    echo "URL: $BASE_URL$path" >&2
    echo "Timeouts: connect=${CONNECT_TIMEOUT}s, total=${max_time}s" >&2
    echo "Curl error:" >&2
    if [[ -s "$error_file" ]]; then
      sed 's/^/  /' "$error_file" >&2
    else
      echo "  <empty>" >&2
    fi
    echo "Response body:" >&2
    if [[ -s "$body_file" ]]; then
      sed 's/^/  /' "$body_file" >&2
    else
      echo "  <empty>" >&2
    fi
    exit 1
  fi

  if [[ "$status" != "$expected_status" ]]; then
    echo "FAIL $name: expected HTTP $expected_status, got $status" >&2
    echo "URL: $BASE_URL$path" >&2
    echo "Response body:" >&2
    sed 's/^/  /' "$body_file" >&2
    exit 1
  fi

  echo "PASS $name ($method $path -> $status)"
  print_response "$body_file"
  PASS_COUNT=$((PASS_COUNT + 1))
  RESPONSE_FILE="$body_file"
}

assert_body_contains() {
  local expected="$1"
  local name="$2"
  if ! grep -Fq "$expected" "$RESPONSE_FILE"; then
    echo "FAIL $name: response did not contain $expected" >&2
    echo "Response body:" >&2
    sed 's/^/  /' "$RESPONSE_FILE" >&2
    exit 1
  fi
}

wait_for_analysis_results() {
  local deadline=$((SECONDS + POLL_TIMEOUT))
  local attempt=1

  while (( SECONDS <= deadline )); do
    request GET "/api/analysis-results?target_date=$TEST_DATE" 200 "analysis results poll #$attempt"
    assert_body_contains '"results": [' "analysis results body on poll #$attempt"

    if ! grep -Fq '"results": []' "$RESPONSE_FILE"; then
      echo "==> Analysis results are available after poll #$attempt"
      return
    fi

    echo "==> No analysis results yet for $TEST_DATE; waiting ${POLL_INTERVAL}s before next poll"
    attempt=$((attempt + 1))
    sleep "$POLL_INTERVAL"
  done

  fail_with_response "analysis results did not appear within ${POLL_TIMEOUT}s" "$RESPONSE_FILE"
}

VALID_CONFIG_BODY='{
  "keywords": ["large language model", "agent", "reasoning"],
  "sources": [
    {
      "id": "arxiv",
      "type": "arxiv",
      "name": "arXiv",
      "enabled": true
    }
  ],
  "domain_rules": [
    {
      "source": "arxiv",
      "category": "cs.RO",
      "mode": "accept_all",
      "filter_categories": []
    }
  ],
  "relevance_threshold": "MEDIUM",
  "openai_model": "deepseek-v4-flash",
  "openai_base_url": "https://api.deepseek.com/v1",
  "output_dir": "output",
  "prompts_dir": "prompts",
  "history_file": "history.json"
}'

echo "==> Running $MODE API tests against $BASE_URL"
echo "==> Timeouts: connect=${CONNECT_TIMEOUT}s, default=${CURL_MAX_TIME}s, run_trigger=${RUN_TRIGGER_MAX_TIME}s, poll_timeout=${POLL_TIMEOUT}s"

request OPTIONS /health 200 "CORS preflight" "" no
assert_body_contains '"ok": true' "CORS preflight body"

request GET /health 200 "authenticated health"
assert_body_contains '"service": "PaperSniffer"' "health body"

request GET /health 401 "missing auth is rejected" "" no
assert_body_contains '"ok": false' "missing auth body"

request GET /config 200 "safe config snapshot"

request GET /api/config 200 "config API read"
assert_body_contains '"ok": true' "config API read body"

request POST /api/config/validate 200 "config validation" "$VALID_CONFIG_BODY"
assert_body_contains '"ok": true' "config validation body"

request POST "/run?date=$TEST_DATE" 202 "pipeline run trigger" "" yes "$RUN_TRIGGER_MAX_TIME"
assert_body_contains '"ok": true' "pipeline run trigger body"
assert_body_contains '"queued": true' "pipeline run trigger queued body"

wait_for_analysis_results

request GET /api/analysis-results 400 "analysis results require target_date"
assert_body_contains 'target_date' "analysis results validation body"

echo "==> All $PASS_COUNT API tests passed."
