#!/usr/bin/env bash
# Deploy the latest main to the EC2 host from your own machine.
#
# Usage: deploy/deploy.sh [ssh-host]
#   ssh-host defaults to $RIO_SSH_HOST (e.g. "ubuntu@1.2.3.4" or a ~/.ssh/config alias).
#
# It runs deploy/bootstrap.sh on the host, the same script used for the first install,
# so a deploy and an install do exactly the same steps (pull, build, migrate, start,
# tunnel, public check). The host keeps its port in /opt/rio/port; pass RIO_HOST_PORT
# only to move it.
set -euo pipefail

SSH_HOST="${1:-${RIO_SSH_HOST:-}}"
if [[ -z "${SSH_HOST}" ]]; then
  echo "error: no ssh host given. Usage: deploy/deploy.sh [ssh-host], or set RIO_SSH_HOST." >&2
  exit 1
fi

echo "==> Deploying to ${SSH_HOST}"
# bootstrap.sh is sent over stdin and run by bash on the host; it wraps itself in main()
# so nothing it runs can consume the rest of the script.
ssh "${SSH_HOST}" "RIO_HOST_PORT='${RIO_HOST_PORT:-}' bash -s" < "$(dirname "$0")/bootstrap.sh"
