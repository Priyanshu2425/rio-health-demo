# Rio: prescription-to-cart demo

A customer sends a photo of a prescription in a WhatsApp-style chat. Rio reads it, matches
each line to a real SKU, builds a cart with cheaper generic alternatives, and puts the
order in front of a pharmacist, who approves it in seconds because every line is marked
green, amber or red. A forecast tab shows demand by SKU, area and hour, with stockout
alerts.

> Status: scaffold. The architecture diagram, accuracy table and "what I'd build next"
> land at H8.

## Layout

```
backend/     FastAPI app. app/contracts.py is the shared data contract.
frontend/    Vite + React + TypeScript
contracts/   API.md, generated schema.json, mock fixtures
data/        catalog seed and Schedule H list
eval/        prescription test sets and the accuracy harness
deploy/      Docker, Cloudflare Tunnel, deploy script
docs/        DECISIONS.md, PLAN.md, agent briefs, per-branch VERIFY files
```

## Run locally

```bash
cp .env.example .env                 # fill in, see docs/briefs/00-you-setup.md
cd backend && uv sync && uv run python -m app.core.migrate && uv run uvicorn app.main:app --reload
cd frontend && npm install && npm run dev
```

With no keys, set `RIO_USE_MOCKS=1` (backend) or `VITE_MOCKS=1` (frontend) to run on the
fixtures in `contracts/fixtures/`.

## Not in this demo

The real WhatsApp Business API, auth, payments and delivery tracking.
