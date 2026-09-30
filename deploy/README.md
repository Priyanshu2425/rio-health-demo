# Deploying rio-api

One EC2 instance runs the FastAPI backend in Docker. Only SSH is open on the
security group; public traffic reaches the box through a Cloudflare Tunnel at
`rio-api.buildspacelabs.com`, which forwards to `http://127.0.0.1:8000`.

Repo lives at `/opt/rio/app` on the server. Environment values live in
`/opt/rio/.env`, outside the repo, `chmod 600`.

A deploy is the code plus the database URL. At runtime the app reads only Neon
(`contracts/README.md` rule 0), so the image holds `backend/` only: no `data/`,
no fixtures. `docker-compose.yml` pins `RIO_USE_MOCKS=0`; mock mode is for
local development and does not work in the image. With mocks off, the app
refuses to start if `RIO_HEALTH_DATABASE_URL` is missing or the database is
unreachable. Check `docker compose ... logs api` if the container keeps
restarting.

**One worker, one container.** The per-IP rate limiter and the startup state
(the background forecast run when `forecast_runs` is empty) live in process
memory. More workers or replicas would split the limiter and run the forecast
bootstrap more than once. Do not raise `--workers` or scale the service.

**`CF-Connecting-IP` is trusted only because of the port binding.** The rate
limiter keys on that header. That is safe only because compose binds the port
to `127.0.0.1`, so every request arrives through the tunnel, where Cloudflare
sets the header. Anyone reaching the port directly could forge it. Never
publish port 8000 on a public interface.

**Database prerequisites.** Neon schema `app_rio_health` must already hold the
catalog (`skus`, loaded by `scripts/etl/build_catalog.py`) and the demo samples
(`samples`, loaded by `eval/load_samples.py`). Those ETL scripts run from a dev
machine, not from this host. `deploy.sh` applies pending migrations on every
deploy.

## One-time server setup

1. Launch an EC2 instance: Ubuntu 24.04, security group allowing inbound SSH
   only (no 80/443).

2. Install Docker and the compose plugin:
   ```
   curl -fsSL https://get.docker.com | sudo sh
   sudo usermod -aG docker "$USER"
   sudo apt-get install -y docker-compose-plugin
   ```
   (log out/in for the group change to apply.)

3. Clone the repo:
   ```
   sudo mkdir -p /opt/rio
   sudo chown "$USER" /opt/rio
   git clone https://github.com/Priyanshu2425/rio-health-demo /opt/rio/app
   ```

4. Create the env file:
   ```
   sudo touch /opt/rio/.env
   sudo chown "$USER" /opt/rio/.env
   chmod 600 /opt/rio/.env
   ```
   Fill in these names (no values here). The first four are required; the
   rest have defaults (10 parses per IP per hour, 5 MB, 45 s, 8000 tokens).
   `RIO_USE_MOCKS` is ignored: compose sets it to 0.
   ```
   RIO_HEALTH_DATABASE_URL=     # direct (non-pooled) Neon endpoint
   OPENROUTER_API_KEY=          # with a monthly spend limit set on the key
   VISION_MODEL=                # e.g. google/gemini-3.8-flash (chosen by eval/)
   RERANK_MODEL=
   PARSE_RATE_LIMIT_PER_HOUR=
   MAX_UPLOAD_MB=
   OPENROUTER_TIMEOUT_S=
   OPENROUTER_MAX_TOKENS=
   ```

5. Install cloudflared:
   ```
   curl -fsSL -o cloudflared.deb \
     https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
   sudo dpkg -i cloudflared.deb
   ```

6. Authenticate and create the tunnel:
   ```
   cloudflared tunnel login
   cloudflared tunnel create rio-api
   cloudflared tunnel route dns rio-api rio-api.buildspacelabs.com
   ```
   Note the tunnel id printed by `tunnel create`.

7. Install the tunnel config and service:
   ```
   sudo mkdir -p /etc/cloudflared
   sudo cp /opt/rio/app/deploy/cloudflared/config.yml.example /etc/cloudflared/config.yml
   # edit /etc/cloudflared/config.yml: replace <TUNNEL_ID> in both lines
   sudo cp ~/.cloudflared/<TUNNEL_ID>.json /etc/cloudflared/<TUNNEL_ID>.json
   sudo cp /opt/rio/app/deploy/cloudflared/cloudflared.service /etc/systemd/system/cloudflared.service
   sudo systemctl daemon-reload
   sudo systemctl enable --now cloudflared
   ```
   The unit runs as root for simplicity (it needs to read the credentials
   file cloudflared writes under `/etc/cloudflared`). To run it as an
   unprivileged `cloudflared` user instead, create the user
   (`sudo useradd --system --no-create-home cloudflared`), `chown` the
   `/etc/cloudflared` files to it, and change `User=root` to
   `User=cloudflared` in the unit before enabling it.

8. First deploy, from your own machine in a local clone of the repo:
   ```
   RIO_SSH_HOST=<your-ssh-alias-or-user@host> deploy/deploy.sh
   ```
   Or run the equivalent commands by hand on the box:
   ```
   cd /opt/rio/app
   docker compose -f deploy/docker-compose.yml up -d --build
   docker compose -f deploy/docker-compose.yml exec -T api python -m app.core.migrate
   curl -fsS http://127.0.0.1:8000/api/health
   ```

9. Verify from your own machine:
   ```
   curl -fsS https://rio-api.buildspacelabs.com/api/health
   ```

## Everyday deploy

From your own machine, with `RIO_SSH_HOST` set (or passed as an argument):
```
deploy/deploy.sh [ssh-host]
```
This pulls the latest `main` on the server, rebuilds and restarts the `api`
container, runs migrations inside it, waits for the local health check, then
checks the public health endpoint from your machine.

## Troubleshooting

- App logs: `docker compose -f deploy/docker-compose.yml logs -f api`
- Tunnel logs: `journalctl -u cloudflared -f`
- Container won't start / crashes on boot: check `/opt/rio/.env` has all the
  required names set and is readable by the `docker` user.
- Health check fails locally but the container is running: exec in and hit
  the endpoint directly (`docker compose -f deploy/docker-compose.yml exec api
  python -c "..."`) since the slim image has no `curl`.
- Public endpoint fails but local health check passes: check `cloudflared`
  is active (`systemctl status cloudflared`) and that the tunnel's DNS route
  still points at `rio-api.buildspacelabs.com`.
- Do not scale to more than one worker/replica; the rate limiter is
  in-memory and only correct for a single process.
