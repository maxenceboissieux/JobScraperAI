#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -P "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd -P "$SCRIPT_DIR/.." && pwd)
FRONTEND_DIR="$PROJECT_ROOT/frontend"
PYTHON="$PROJECT_ROOT/.venv/bin/python"
JOBSCRAPER="$PROJECT_ROOT/.venv/bin/jobscraper"
SERVER_PID=""

cleanup() {
  cleanup_status=$?
  trap - 0 1 2 15
  if [ -n "$SERVER_PID" ] && kill -0 "$SERVER_PID" 2>/dev/null; then
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
  rm -rf "$E2E_TEMP_DIR"
  exit "$cleanup_status"
}

http_ready() {
  "$PYTHON" -c \
    'import sys; from urllib.request import urlopen; response = urlopen(sys.argv[1], timeout=0.25); response.close(); raise SystemExit(0 if response.status == 200 else 1)' \
    "$1"
}

if [ ! -x "$PYTHON" ] || [ ! -x "$JOBSCRAPER" ]; then
  echo "Environnement Python absent : créez .venv et installez le projet." >&2
  exit 1
fi

if ! command -v node >/dev/null 2>&1; then
  CODEX_NODE_DIR=${JOBSCRAPER_NODE_DIR:-"$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin"}
  if [ ! -x "$CODEX_NODE_DIR/node" ]; then
    echo "Node.js est introuvable; définissez JOBSCRAPER_NODE_DIR." >&2
    exit 1
  fi
  PATH="$CODEX_NODE_DIR:$PATH"
  export PATH
fi

E2E_TEMP_DIR=$(mktemp -d "${TMPDIR:-/tmp}/jobscraper-e2e.XXXXXX")
trap cleanup 0
trap 'exit 129' 1
trap 'exit 130' 2
trap 'exit 143' 15

JOBSCRAPER_DATABASE_URL="sqlite:///$E2E_TEMP_DIR/jobscraper.db"
JOBSCRAPER_E2E_ARTIFACTS="$E2E_TEMP_DIR/playwright-artifacts"
JOBSCRAPER_FAKE_DETAIL_LOG="$E2E_TEMP_DIR/detail-calls.log"
JOBSCRAPER_FAKE_NOW=$(
  "$PYTHON" -c 'from datetime import datetime, timezone; print(datetime.now(timezone.utc).replace(microsecond=0).isoformat())'
)
JOBSCRAPER_ENV="test"
JOBSCRAPER_SCRAPER_MODE="fake"
HTTP_PROXY="http://127.0.0.1:1"
HTTPS_PROXY="http://127.0.0.1:1"
ALL_PROXY="http://127.0.0.1:1"
NO_PROXY="127.0.0.1,localhost"
PYTHONPATH="$PROJECT_ROOT${PYTHONPATH:+:$PYTHONPATH}"
export JOBSCRAPER_DATABASE_URL JOBSCRAPER_E2E_ARTIFACTS
export JOBSCRAPER_FAKE_DETAIL_LOG JOBSCRAPER_FAKE_NOW
export JOBSCRAPER_ENV JOBSCRAPER_SCRAPER_MODE
export HTTP_PROXY HTTPS_PROXY ALL_PROXY NO_PROXY PYTHONPATH

cd "$FRONTEND_DIR"
pnpm build

FORBIDDEN_DATABASE="$E2E_TEMP_DIR/forbidden.db"
if forbidden_output=$(
  env \
    JOBSCRAPER_ENV=production \
    JOBSCRAPER_SCRAPER_MODE=fake \
    "$PYTHON" -c \
      'from jobscraper.runtime import build_runtime; build_runtime(__import__("sys").argv[1])' \
      "sqlite:///$FORBIDDEN_DATABASE" 2>&1
); then
  echo "Le mode fake a été accepté dans l’environnement production." >&2
  exit 1
fi
case "$forbidden_output" in
  *"Le mode fake est interdit dans l’environnement production."*) ;;
  *)
    printf '%s\n' "$forbidden_output" >&2
    echo "Le refus production du mode fake n’est pas explicite." >&2
    exit 1
    ;;
esac
if [ -e "$FORBIDDEN_DATABASE" ]; then
  echo "Le mode fake production a touché la base avant son refus." >&2
  exit 1
fi

server_start_attempt=0
server_ready=0
while [ "$server_start_attempt" -lt 5 ]; do
  server_start_attempt=$((server_start_attempt + 1))
  PORT=$(
    "$PYTHON" -c 'import socket; sock = socket.socket(); sock.bind(("127.0.0.1", 0)); print(sock.getsockname()[1]); sock.close()'
  )
  JOBSCRAPER_E2E_BASE_URL="http://127.0.0.1:$PORT"
  export JOBSCRAPER_E2E_BASE_URL

  "$JOBSCRAPER" serve --host 127.0.0.1 --port "$PORT" --no-open \
    >"$E2E_TEMP_DIR/server.log" 2>&1 &
  SERVER_PID=$!

  readiness_attempt=0
  while [ "$readiness_attempt" -lt 300 ]; do
    if http_ready "$JOBSCRAPER_E2E_BASE_URL/api/searches" >/dev/null 2>&1; then
      server_ready=1
      break
    fi
    if ! kill -0 "$SERVER_PID" 2>/dev/null; then
      wait "$SERVER_PID" 2>/dev/null || true
      SERVER_PID=""
      break
    fi
    readiness_attempt=$((readiness_attempt + 1))
    sleep 0.1
  done
  if [ "$server_ready" -eq 1 ]; then
    break
  fi
  if [ -n "$SERVER_PID" ] && kill -0 "$SERVER_PID" 2>/dev/null; then
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
    SERVER_PID=""
  fi
done

if [ "$server_ready" -ne 1 ]; then
  cat "$E2E_TEMP_DIR/server.log" >&2
  echo "Le serveur E2E n’est pas prêt après cinq tentatives bornées." >&2
  exit 1
fi

pnpm exec playwright test --config playwright.config.ts
