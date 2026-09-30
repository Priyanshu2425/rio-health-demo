# Deploying rio-api

One EC2 instance runs the FastAPI backend in Docker. Only SSH is open on the
security group; public traffic reaches the box through a Cloudflare Tunnel at
`rio-api.buildspacelabs.com`, which forwards to `http://127.0.0.1:8000`.

Repo lives at `/opt/rio/app` on the server. Environment values live in
`/opt/rio/.env`, outside the repo, `chmod 600`.

The app runs as a single uvicorn worker. Its rate limiter is in-memory, so
running more than one worker or replica would let requests dodge the limit.
Do not raise `--workers` or scale the compose service without changing that.

The rate limiter keys on the `CF-Connecting-IP` header. That is only safe
because the port is bound to `127.0.0.1`, so every request arrives through the
tunnel, where Cloudflare sets the header. Never publish port 8000 publicly.

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
   Fill in these names (no values here):
   ```
   RIO_HEALTH_DATABASE_URL=
   OPENROUTER_API_KEY=
   VISION_MODEL=
   RERANK_MODEL=
   RIO_USE_MOCKS=
   PARSE_RATE_LIMIT_PER_HOUR=
   MAX_UPLOAD_MB=
   OPENROUTER_TIMEOUT_S=
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
