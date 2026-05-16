#!/usr/bin/env bash
# Deploy backend first, pass its Worker URL to the frontend, then deploy frontend.
#
# Usage:
#   OPENAI_API_KEY=sk-... ADMIN_TOKEN=... bash script/deploy-workers.sh
#
# Optional:
#   BACKEND_BASE_URL=https://paper-sniffer-backend.example.workers.dev
#   APP_TITLE=PaperSniffer

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DEPLOY="$ROOT/backend/script/deploy.sh"
FRONTEND_DEPLOY="$ROOT/frontend/script/deploy.sh"

require_env() {
  local missing=()

  for key in OPENAI_API_KEY ADMIN_TOKEN; do
    if [[ -z "${!key+x}" ]] || [[ -z "${!key}" ]]; then
      missing+=("$key")
    fi
  done

  if (( ${#missing[@]} > 0 )); then
    echo "Error: missing required environment variable(s): ${missing[*]}" >&2
    echo "Usage: OPENAI_API_KEY=sk-... ADMIN_TOKEN=... bash script/deploy-workers.sh" >&2
    exit 1
  fi
}

extract_worker_url() {
  local log_file="$1"
  local workers_url
  workers_url="$(
    grep -Eo 'https://[^[:space:]]+' "$log_file" \
      | grep 'workers\.dev' \
      | sed 's/[),.;]$//' \
      | tail -n 1 \
      || true
  )"

  if [[ -n "$workers_url" ]]; then
    echo "$workers_url"
    return
  fi

  grep -Eo 'https://[^[:space:]]+' "$log_file" \
    | sed 's/[),.;]$//' \
    | tail -n 1 \
    || true
}

require_env

backend_log="$(mktemp)"
frontend_log="$(mktemp)"
trap 'rm -f "$backend_log" "$frontend_log"' EXIT

cd "$ROOT"

echo "==> Deploying backend Worker"
bash "$BACKEND_DEPLOY" cloud | tee "$backend_log"

backend_url="${BACKEND_BASE_URL:-}"
if [[ -z "$backend_url" ]]; then
  backend_url="$(extract_worker_url "$backend_log")"
fi

if [[ -z "$backend_url" ]]; then
  echo "Error: could not determine backend Worker URL from deploy output." >&2
  echo "Set BACKEND_BASE_URL explicitly and rerun this script." >&2
  exit 1
fi

echo "==> Backend URL for frontend: $backend_url"
echo "==> Deploying frontend Worker"
BACKEND_ADMIN_TOKEN="$ADMIN_TOKEN" \
APP_TITLE="${APP_TITLE:-PaperSniffer}" \
  bash "$FRONTEND_DEPLOY" cloud | tee "$frontend_log"

frontend_url="$(extract_worker_url "$frontend_log")"

echo "==> Deployment completed"
echo "    Backend:  $backend_url"
if [[ -n "$frontend_url" ]]; then
  echo "    Frontend: $frontend_url"
else
  echo "    Frontend: check Wrangler output above for the deployed URL"
fi
