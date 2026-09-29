# 00: Your setup (H0–H1)

These steps need your accounts. Agents can't do them. Tick them off in order; the agents
start once 1–4 are done.

## 1. Review and push `main`

```bash
cd ~/Desktop/buildspace/rio_health
git log --stat                                   # the scaffold commit
cd backend && uv sync && uv run pytest -q        # expect all green
cd ../frontend && npm install && npm run gen:contracts -- --check && npm run build
cd .. && gh repo create rio-health-demo --public --source . --push
```

## 2. Neon (about 5 min)

```bash
cd ~/Desktop/buildspace/neon
.venv/bin/python -m scripts.provision rio_health \
    --repo ~/Desktop/buildspace/rio_health --pooling direct \
    --migrations "backend/migrations, applied by: uv run python -m app.core.migrate" \
    --secret-location "repo .env; EC2 /opt/rio/.env"
```

Then, as admin (with `NEON_ADMIN_URL` from `neon/.env`), install `pg_trgm` database-wide.
It lives in `public` as functions and operators, like pgvector, so `public` still has no
relations:

```sql
CREATE EXTENSION IF NOT EXISTS pg_trgm;
```

Then:

```bash
.venv/bin/python -m scripts.verify                       # exit 0
cd ~/Desktop/buildspace/rio_health/backend && uv run python -m app.core.migrate
```

## 3. OpenRouter (about 3 min)

Create a key at openrouter.ai/keys, **set a credit limit on it** (for example $10), and
put it in `.env` as `OPENROUTER_API_KEY`. Leave `VISION_MODEL` and `RERANK_MODEL` empty;
the parser agent's eval picks them.

## 4. Kaggle data (about 5 min)

Download the **"A-Z Medicine Dataset of India"** CSV from Kaggle, either in the browser or
with `kaggle datasets download` if you have `~/.kaggle/kaggle.json`. Put the CSV at
`data/raw/` (gitignored). Note the dataset's license for the README.

## 5. EC2 (about 15 min; needed by H4, not by H1)

- One `t4g.small` (ARM) or `t3.small`, running Ubuntu 24.04, with an Elastic IP. The
  security group allows **SSH only**, from your IP.
- Install `docker` and `docker compose`, and `git clone` the repo to `/opt/rio`.
- Create `/opt/rio/.env` with the same values as your local `.env`.

## 6. Cloudflare (about 10 min; needed by H4)

- **Tunnel:** on EC2, install `cloudflared`, run `cloudflared tunnel login`, create a
  tunnel named `rio`, and route `rio-api.buildspacelabs.com` → `http://localhost:8000`.
  The backend agent's `deploy/` has the config file and a systemd unit; you run the
  login, since it opens a browser.
- **Pages:** create a project from the GitHub repo with root `frontend/`, build command
  `npm run build`, output `dist`, and env `VITE_API_BASE_URL=https://rio-api.buildspacelabs.com`.
  Add the custom domain `rio.buildspacelabs.com`.

## 7. Handwritten prescriptions (about 30 min; needed by H4)

Write 10 prescriptions on paper in 2–3 different hands. Mix clear and messy handwriting,
use 2–5 lines each, and use real brand names (Augmentin, Pan 40, Dolo, Montair, Azithral,
Telma…). Photograph them with your phone and put them in `eval/handwritten/` as
`hw_01.jpg`…. The parser agent's brief describes the ground-truth file you fill in with
each one. Use no real patient data.
