#!/usr/bin/env bash
# Install or update rio-api on THIS machine, next to other apps, and expose it through
# its own Cloudflare Tunnel at rio-api.buildspacelabs.com.
#
# Run on the EC2 host (Ubuntu), as a user with sudo:
#   curl -fsSL https://raw.githubusercontent.com/Priyanshu2425/rio-health-demo/main/deploy/bootstrap.sh | bash
# or, once the repo is cloned:
#   bash /opt/rio/app/deploy/bootstrap.sh
#
# Safe to re-run: every step checks before it acts. It never touches other containers,
# other cloudflared tunnels or /etc/cloudflared (another app may own those).
#
# Settings (environment variables):
#   RIO_HOST_PORT  local port for the API, bound to 127.0.0.1 (default 8001)
#   RIO_HOSTNAME   public hostname (default rio-api.buildspacelabs.com)
#   RIO_BRANCH     git branch to deploy (default main)
set -euo pipefail

REPO=https://github.com/Priyanshu2425/rio-health-demo.git
BASE=/opt/rio
APP_DIR=$BASE/app
ENV_FILE=$BASE/.env
PORT="${RIO_HOST_PORT:-8001}"
HOSTNAME_PUBLIC="${RIO_HOSTNAME:-rio-api.buildspacelabs.com}"
BRANCH="${RIO_BRANCH:-main}"
TUNNEL=rio-api
CF_DIR=/etc/cloudflared-rio          # separate from /etc/cloudflared on purpose
CF_SERVICE=cloudflared-rio
COMPOSE=(sudo env RIO_HOST_PORT="$PORT" docker compose -f "$APP_DIR/deploy/docker-compose.yml")

step() { printf '\n==> %s\n' "$*"; }
die() { printf '\nerror: %s\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------------------
step "Checking tools"
command -v sudo >/dev/null || die "sudo is required"
if ! command -v git >/dev/null; then
  sudo apt-get update -qq && sudo apt-get install -y -qq git
fi
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sudo sh
fi
sudo docker compose version >/dev/null 2>&1 || sudo apt-get install -y -qq docker-compose-plugin
if ! command -v cloudflared >/dev/null; then
  arch=$(dpkg --print-architecture)
  curl -fsSL -o /tmp/cloudflared.deb \
    "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${arch}.deb"
  sudo dpkg -i /tmp/cloudflared.deb
  rm -f /tmp/cloudflared.deb
fi
echo "git, docker, compose and cloudflared are present"

# ---------------------------------------------------------------------------
step "Checking port $PORT"
owner=$(sudo docker ps --format '{{.Names}} {{.Ports}}' | grep -E "127\.0\.0\.1:${PORT}->|0\.0\.0\.0:${PORT}->" | awk '{print $1}' || true)
if [[ -n "$owner" && "$owner" != "rio-api" ]]; then
  die "port $PORT is used by container '$owner'. Re-run with RIO_HOST_PORT=<free port>."
fi
if [[ -z "$owner" ]] && sudo ss -ltn "( sport = :$PORT )" | grep -q LISTEN; then
  die "port $PORT is in use by another process. Re-run with RIO_HOST_PORT=<free port>."
fi
echo "port $PORT is free or already Rio's"

# ---------------------------------------------------------------------------
step "Fetching code into $APP_DIR ($BRANCH)"
sudo mkdir -p "$BASE"
sudo chown "$USER" "$BASE"
if [[ -d "$APP_DIR/.git" ]]; then
  git -C "$APP_DIR" fetch -q origin "$BRANCH"
  git -C "$APP_DIR" checkout -q "$BRANCH"
  git -C "$APP_DIR" pull -q --ff-only origin "$BRANCH"
else
  git clone -q --branch "$BRANCH" "$REPO" "$APP_DIR"
fi
echo "at $(git -C "$APP_DIR" log --oneline -1)"

# ---------------------------------------------------------------------------
step "Checking $ENV_FILE"
if [[ ! -s "$ENV_FILE" ]]; then
  cat >&2 <<EOF

$ENV_FILE is missing. Create it, then re-run this script:

  nano $ENV_FILE        # paste the lines below with your values
  chmod 600 $ENV_FILE

  RIO_HEALTH_DATABASE_URL=...      (the direct Neon URL from your local .env)
  OPENROUTER_API_KEY=...
  VISION_MODEL=google/gemini-3.8-flash
  RERANK_MODEL=openai/gpt-6-luna
  PARSE_RATE_LIMIT_PER_HOUR=10
  MAX_UPLOAD_MB=5
EOF
  exit 1
fi
chmod 600 "$ENV_FILE"
for key in RIO_HEALTH_DATABASE_URL OPENROUTER_API_KEY VISION_MODEL; do
  grep -Eq "^${key}=.+" "$ENV_FILE" || die "$ENV_FILE has no value for $key"
done
echo "env file has the required keys (values not shown)"

# ---------------------------------------------------------------------------
step "Building, migrating and starting rio-api on 127.0.0.1:$PORT"
"${COMPOSE[@]}" build
# Migrate before the new app starts, so its startup forecast check sees every table.
"${COMPOSE[@]}" run --rm --no-deps api python -m app.core.migrate
"${COMPOSE[@]}" up -d
for i in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:$PORT/api/health" >/tmp/rio-health.json 2>/dev/null; then
    echo "local health: $(cat /tmp/rio-health.json)"
    break
  fi
  [[ $i == 30 ]] && { "${COMPOSE[@]}" logs --tail 50 api; die "rio-api did not become healthy in 60 s"; }
  sleep 2
done

# ---------------------------------------------------------------------------
step "Cloudflare Tunnel '$TUNNEL' for $HOSTNAME_PUBLIC"
CF_HOME=/root/.cloudflared
if ! sudo test -f "$CF_HOME/cert.pem"; then
  cat <<EOF

cloudflared needs a one-time login. It prints a URL: open it in your browser,
pick the buildspacelabs.com zone and authorize. This script continues after that.
EOF
  sudo cloudflared tunnel login
else
  echo "reusing the existing cloudflared login ($CF_HOME/cert.pem). It must be for the"
  echo "buildspacelabs.com zone, or the DNS route below lands in the wrong zone."
fi
if ! sudo cloudflared tunnel list --name "$TUNNEL" 2>/dev/null | grep -q "$TUNNEL"; then
  sudo cloudflared tunnel create "$TUNNEL"
fi
TUNNEL_ID=$(sudo cloudflared tunnel list --name "$TUNNEL" --output json | python3 -c "import json,sys; print(json.load(sys.stdin)[0]['id'])")
# Points the hostname at this tunnel; leaves an existing correct record alone.
sudo cloudflared tunnel route dns "$TUNNEL" "$HOSTNAME_PUBLIC" || true

sudo mkdir -p "$CF_DIR"
sudo cp "$CF_HOME/$TUNNEL_ID.json" "$CF_DIR/$TUNNEL_ID.json"
sudo tee "$CF_DIR/config.yml" >/dev/null <<EOF
tunnel: $TUNNEL_ID
credentials-file: $CF_DIR/$TUNNEL_ID.json
ingress:
  - hostname: $HOSTNAME_PUBLIC
    service: http://127.0.0.1:$PORT
  - service: http_status:404
EOF
sudo tee "/etc/systemd/system/$CF_SERVICE.service" >/dev/null <<EOF
[Unit]
Description=Cloudflare Tunnel for $HOSTNAME_PUBLIC
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=$(command -v cloudflared) --no-autoupdate --config $CF_DIR/config.yml tunnel run
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now "$CF_SERVICE"
sudo systemctl restart "$CF_SERVICE"

# ---------------------------------------------------------------------------
step "Checking https://$HOSTNAME_PUBLIC/api/health"
for i in $(seq 1 20); do
  if curl -fsS "https://$HOSTNAME_PUBLIC/api/health"; then
    printf '\n\nrio-api is live at https://%s (local port %s)\n' "$HOSTNAME_PUBLIC" "$PORT"
    exit 0
  fi
  sleep 3
done
die "the tunnel did not answer in 60 s. Check: sudo systemctl status $CF_SERVICE; sudo journalctl -u $CF_SERVICE -n 50"
