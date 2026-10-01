#!/usr/bin/env bash
# Install or update rio-api on THIS machine, next to other apps, and expose it through
# its own Cloudflare Tunnel at rio-api.buildspacelabs.com.
#
# Run on the EC2 host (Ubuntu), as a user with sudo:
#   curl -fsSL https://raw.githubusercontent.com/Priyanshu2425/rio-health-demo/main/deploy/bootstrap.sh | bash
#
# Safe to re-run; deploy/deploy.sh runs exactly this over ssh for later deploys. It never
# touches other containers (the compose project is named "rio"), other cloudflared
# tunnels, /etc/cloudflared or cloudflared.service (another app may own those).
#
# Settings (environment variables):
#   RIO_HOST_PORT  local port for the API, bound to 127.0.0.1. Default: the port saved by
#                  the previous run in /opt/rio/port, else 8001.
#   RIO_HOSTNAME   public hostname (default rio-api.buildspacelabs.com)
#   RIO_BRANCH     git branch to deploy (default main)
set -euo pipefail

# Everything lives in main(), called on the last line: under `curl | bash`, bash then
# reads the whole script before running any of it, so no command can swallow the rest.
main() {
  local REPO=https://github.com/Priyanshu2425/rio-health-demo.git
  local BASE=/opt/rio
  local APP_DIR=$BASE/app
  local ENV_FILE=$BASE/.env
  local PORT_FILE=$BASE/port
  local HOSTNAME_PUBLIC="${RIO_HOSTNAME:-rio-api.buildspacelabs.com}"
  local BRANCH="${RIO_BRANCH:-main}"
  local TUNNEL=rio-api
  local CF_DIR=/etc/cloudflared-rio        # separate from /etc/cloudflared on purpose
  local CF_SERVICE=cloudflared-rio
  local ME="${USER:-$(id -un)}"
  local PORT
  PORT="${RIO_HOST_PORT:-}"
  [[ -n "$PORT" ]] || PORT=$(cat "$PORT_FILE" 2>/dev/null || echo 8001)
  local -a COMPOSE=(sudo env RIO_HOST_PORT="$PORT" docker compose -p rio -f "$APP_DIR/deploy/docker-compose.yml")

  # -------------------------------------------------------------------------
  step "Checking tools"
  command -v sudo >/dev/null || die "sudo is required"
  if ! command -v git >/dev/null; then
    sudo apt-get update -qq </dev/null && sudo apt-get install -y -qq git </dev/null
  fi
  if ! command -v docker >/dev/null; then
    curl -fsSL https://get.docker.com | sudo sh
  fi
  sudo docker compose version >/dev/null 2>&1 || sudo apt-get install -y -qq docker-compose-plugin </dev/null
  if ! command -v cloudflared >/dev/null; then
    local deb
    deb=$(mktemp --suffix=.deb)
    curl -fsSL -o "$deb" \
      "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-$(dpkg --print-architecture).deb"
    sudo dpkg -i "$deb" </dev/null
    rm -f "$deb"
  fi
  echo "git, docker, compose and cloudflared are present"

  # -------------------------------------------------------------------------
  step "Checking port $PORT"
  local bindings owner listeners
  bindings=$(sudo docker ps --format '{{.Names}} {{.Ports}}')
  owner=$(awk -v p=":${PORT}->" 'index($0, p) {print $1}' <<<"$bindings")
  if [[ -n "$owner" && "$owner" != "rio-api" ]]; then
    die "port $PORT is used by container '$owner'. Re-run with RIO_HOST_PORT=<free port>."
  fi
  if [[ -z "$owner" ]]; then
    listeners=$(sudo ss -Hltn "( sport = :$PORT )")
    [[ -z "$listeners" ]] || die "port $PORT is in use by another process. Re-run with RIO_HOST_PORT=<free port>."
  fi
  echo "port $PORT is free or already Rio's"

  # -------------------------------------------------------------------------
  step "Fetching code into $APP_DIR ($BRANCH)"
  sudo mkdir -p "$BASE"
  sudo chown "$ME" "$BASE"
  if [[ -d "$APP_DIR/.git" ]]; then
    git -C "$APP_DIR" fetch -q origin "$BRANCH"
    git -C "$APP_DIR" checkout -q "$BRANCH"
    git -C "$APP_DIR" pull -q --ff-only origin "$BRANCH"
  else
    git clone -q --branch "$BRANCH" "$REPO" "$APP_DIR"
  fi
  echo "at $(git -C "$APP_DIR" log --oneline -1)"

  # -------------------------------------------------------------------------
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
EOF
    exit 1
  fi
  chmod 600 "$ENV_FILE"
  local key
  for key in RIO_HEALTH_DATABASE_URL OPENROUTER_API_KEY VISION_MODEL RERANK_MODEL; do
    grep -Eq "^${key}=.+" "$ENV_FILE" || die "$ENV_FILE has no value for $key"
  done
  echo "env file has the required keys (values not shown)"

  # -------------------------------------------------------------------------
  step "Building, migrating and starting rio-api on 127.0.0.1:$PORT"
  "${COMPOSE[@]}" build </dev/null
  # Migrate before the new app starts, so its startup forecast check sees every table.
  "${COMPOSE[@]}" run --rm -T --no-deps api python -m app.core.migrate </dev/null
  "${COMPOSE[@]}" up -d </dev/null
  echo "$PORT" | sudo tee "$PORT_FILE" >/dev/null
  local local_health="" i
  for i in $(seq 1 30); do
    if local_health=$(curl -fsS "http://127.0.0.1:$PORT/api/health" 2>/dev/null); then
      echo "local health: $local_health"
      break
    fi
    if [[ $i == 30 ]]; then
      "${COMPOSE[@]}" logs --tail 50 api </dev/null
      die "rio-api did not become healthy in 60 s"
    fi
    sleep 2
  done

  # -------------------------------------------------------------------------
  step "Cloudflare Tunnel '$TUNNEL' for $HOSTNAME_PUBLIC"
  local CF_HOME=/root/.cloudflared
  if ! sudo test -f "$CF_HOME/cert.pem"; then
    cat <<EOF

cloudflared needs a one-time login. It prints a URL: open it in your browser,
pick the buildspacelabs.com zone and authorize. This script continues after that.
EOF
    sudo cloudflared tunnel login </dev/null
  else
    echo "reusing the existing cloudflared login ($CF_HOME/cert.pem). It must be for the"
    echo "buildspacelabs.com zone; the DNS step below fails loudly if it is not."
  fi
  if ! sudo cloudflared tunnel list --name "$TUNNEL" --output json </dev/null | grep -q '"id"'; then
    sudo cloudflared tunnel create "$TUNNEL" </dev/null
  fi
  local TUNNEL_ID creds src
  TUNNEL_ID=$(sudo cloudflared tunnel list --name "$TUNNEL" --output json </dev/null |
    python3 -c "import json,sys; print(json.load(sys.stdin)[0]['id'])")
  creds="$CF_DIR/$TUNNEL_ID.json"
  if ! sudo test -f "$creds"; then
    src=""
    for c in "$CF_HOME/$TUNNEL_ID.json" "/home/$ME/.cloudflared/$TUNNEL_ID.json"; do
      if sudo test -f "$c"; then src=$c; break; fi
    done
    [[ -n "$src" ]] || die "tunnel $TUNNEL exists but its credentials file $TUNNEL_ID.json was not found.
Delete the tunnel (sudo cloudflared tunnel delete $TUNNEL) and re-run, or copy the file to $CF_DIR."
    sudo mkdir -p "$CF_DIR"
    sudo cp "$src" "$creds"
    sudo chmod 600 "$creds"
  fi
  # Point the hostname at this tunnel. --overwrite-dns only replaces the record for this
  # one hostname; a cert for the wrong zone or any other failure stops the script here.
  sudo cloudflared tunnel route dns --overwrite-dns "$TUNNEL" "$HOSTNAME_PUBLIC" </dev/null

  sudo tee "$CF_DIR/config.yml" >/dev/null <<EOF
tunnel: $TUNNEL_ID
credentials-file: $creds
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
  sudo systemctl enable "$CF_SERVICE" >/dev/null
  sudo systemctl restart "$CF_SERVICE"   # picks up a changed config on re-runs

  # -------------------------------------------------------------------------
  # /api/samples exists only in Rio, so a 200 with a JSON list proves the hostname
  # reaches this container and not another app behind another tunnel.
  step "Checking https://$HOSTNAME_PUBLIC reaches this rio-api"
  local body
  for i in $(seq 1 20); do
    if body=$(curl -fsS "https://$HOSTNAME_PUBLIC/api/samples" 2>/dev/null) && [[ "$body" == "["* ]]; then
      printf 'public health: %s\n' "$(curl -fsS "https://$HOSTNAME_PUBLIC/api/health")"
      printf '\nrio-api is live at https://%s (local port %s)\n' "$HOSTNAME_PUBLIC" "$PORT"
      return 0
    fi
    sleep 3
  done
  die "https://$HOSTNAME_PUBLIC did not reach rio-api in 60 s. rio-api itself is running on
127.0.0.1:$PORT. Check: sudo systemctl status $CF_SERVICE; sudo journalctl -u $CF_SERVICE -n 50"
}

step() { printf '\n==> %s\n' "$*"; }
die() { printf '\nerror: %s\n' "$*" >&2; exit 1; }

main "$@"
