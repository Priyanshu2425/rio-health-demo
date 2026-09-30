#!/usr/bin/env bash
# Deploy the current main branch to the EC2 host and verify it came up.
#
# Usage: deploy/deploy.sh [ssh-host]
#   ssh-host defaults to $RIO_SSH_HOST (e.g. "ubuntu@1.2.3.4" or a ~/.ssh/config
#   alias). Errors out if neither is given.
set -euo pipefail

SSH_HOST="${1:-${RIO_SSH_HOST:-}}"
if [[ -z "${SSH_HOST}" ]]; then
  echo "error: no ssh host given. Usage: deploy/deploy.sh [ssh-host], or set RIO_SSH_HOST." >&2
  exit 1
fi

APP_DIR=/opt/rio/app
COMPOSE="docker compose -f deploy/docker-compose.yml"

echo "==> Deploying to ${SSH_HOST} (${APP_DIR})"

ssh "${SSH_HOST}" "set -euo pipefail
  cd '${APP_DIR}'
  git pull --ff-only
  ${COMPOSE} build
  # Migrate before the new app starts, so its startup forecast check sees every table.
  ${COMPOSE} run --rm --no-deps api python -m app.core.migrate
  ${COMPOSE} up -d
  echo '==> Waiting for local health check'
  for i in \$(seq 1 15); do
    if curl -fsS http://127.0.0.1:8000/api/health; then
      echo
      exit 0
    fi
    sleep 2
  done
  echo 'error: api did not become healthy within 30s' >&2
  exit 1
"

echo "==> Checking public health endpoint"
curl -fsS https://rio-api.buildspacelabs.com/api/health
echo
echo "==> Deploy complete"
