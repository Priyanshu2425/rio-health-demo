#!/usr/bin/env bash
# Pull the latest code and restart rio-api on THIS machine. For a host already set up by
# bootstrap.sh; it does not touch tools, the tunnel or /opt/rio/.env.
#
#   bash /opt/rio/app/deploy/redeploy.sh            # latest main
#   RIO_BRANCH=some-branch bash /opt/rio/app/deploy/redeploy.sh
set -euo pipefail

# Wrapped in main() so a `git pull` that rewrites this file mid-run cannot change what runs.
main() {
  local APP_DIR=/opt/rio/app
  local BRANCH="${RIO_BRANCH:-main}"
  local PORT
  PORT=$(cat /opt/rio/port 2>/dev/null || echo 8001)
  local -a COMPOSE=(sudo env RIO_HOST_PORT="$PORT" docker compose -p rio -f "$APP_DIR/deploy/docker-compose.yml")

  [[ -s /opt/rio/.env ]] || { echo "error: /opt/rio/.env is missing; run deploy/bootstrap.sh first" >&2; exit 1; }

  echo "==> Pulling $BRANCH"
  local before
  before=$(git -C "$APP_DIR" rev-parse --short HEAD)
  git -C "$APP_DIR" fetch -q origin "$BRANCH"
  git -C "$APP_DIR" checkout -q "$BRANCH"
  git -C "$APP_DIR" pull -q --ff-only origin "$BRANCH"
  echo "$before -> $(git -C "$APP_DIR" log --oneline -1)"

  echo "==> Building, migrating, restarting on 127.0.0.1:$PORT"
  "${COMPOSE[@]}" build </dev/null
  "${COMPOSE[@]}" run --rm -T --no-deps api python -m app.core.migrate </dev/null
  "${COMPOSE[@]}" up -d </dev/null

  echo "==> Health"
  local i
  for i in $(seq 1 30); do
    if curl -fsS "http://127.0.0.1:$PORT/api/health" && curl -fsS -o /dev/null "http://127.0.0.1:$PORT/api/samples"; then
      printf '\nrio-api updated and healthy on 127.0.0.1:%s\n' "$PORT"
      return 0
    fi
    sleep 2
  done
  "${COMPOSE[@]}" logs --tail 50 api </dev/null
  echo "error: rio-api did not become healthy in 60 s" >&2
  exit 1
}

main "$@"
