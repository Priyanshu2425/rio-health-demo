# 03: Backend API (`feat/backend-api`)

Read first: `docs/DECISIONS.md`, `contracts/README.md`, `contracts/API.md` (the whole
thing), `backend/app/contracts.py`, `backend/app/main.py`, `backend/app/core/`.

## You own

`backend/app/api/`, `backend/app/orders/`, `backend/app/main.py` (you may add routers,
middleware and startup hooks), `deploy/`, `backend/tests/api/`, `backend/tests/orders/`,
`docs/verify/feat-backend-api.md`. Touch nothing else. Stop and report if you need a
contract change.

## Wave 1 (H1–H4): every route, on mocks

1. **Implement every route in `contracts/API.md`.** When `RIO_USE_MOCKS=1`, the catalog,
   parser and forecast calls are replaced by a mock layer (`app/orders/mocks.py`) that
   serves `contracts/fixtures/`. Orders are still created, stored and moved through their
   states: in memory if there's no database, in Postgres if there is. The frontend must be
   able to run the whole demo against your mock mode.
2. **`app/orders/`**, the heart of it:
   - `build_cart(conn, parsed_rx | text)`: for each line, `match_line`, then
     `quantity_packs`, generic alternative (`cheapest_generic`), savings, and confidence
     plus triage, exactly per the order rules in `contracts/API.md`. Write the rules as
     pure functions with table-driven tests.
   - The state machine: allowed transitions only, otherwise 409 `invalid_transition`.
   - The text flow: `confirmed_otc` vs `needs_prescription`.
   - Review: apply `ItemDecision`s (edit swaps the SKU via `get_sku` and recomputes the
     line), recompute totals, set `reviewed_at`.
   - The queue ordering: worst triage, then oldest.
3. **Uploads:** check the content type and magic bytes; 413 over `MAX_UPLOAD_MB`; store
   bytes in `orders.image`.
4. **Rate limit:** in-memory, per client IP. Behind the tunnel, use `CF-Connecting-IP`,
   falling back to the peer address. Apply it to `POST /api/orders/prescription` only.
5. **Parser errors:** `LLMError` → 502 `parser_failed`; a timeout → 504 `parser_timeout`.
   Never 500 with a stack trace.

## Wave 2 (H4–H7): real modules and deploy

1. Rebase on `main` after data and parser merge. With `RIO_USE_MOCKS=0`, run the real
   pipeline against Neon. Fix integration issues on your side and report ones that belong
   to other modules.
2. **Startup:** if `forecast_runs` is empty, call `app.forecast.run` once.
3. **`deploy/`:**
   - `Dockerfile` (uv, non-root, `uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1`)
   - `docker-compose.yml` bound to `127.0.0.1:${RIO_HOST_PORT:-8001}` (8000 belongs to another app on the shared host)
   - `cloudflared/config.yml.example` for `rio-api.buildspacelabs.com`, and a systemd unit
   - `deploy.sh` (ssh → `git pull` → `docker compose up -d --build` → migrate → curl health)
   - `deploy/README.md` with the owner's one-time steps
4. Deploy and prove it: `curl https://rio-api.buildspacelabs.com/api/health`, and one sample
   order end to end through the public URL.

## Done means

- `uv run pytest -q` is green. API tests run in mock mode with no database; orders tests
  are pure.
- `docs/verify/feat-backend-api.md` has a curl script that walks the whole flow: sample
  order → queue → review with one edit → verified → place. It shows the expected
  statuses, for both mock mode and live.
- Push the branch and open the PR after Wave 1 as a draft; mark it ready after Wave 2.

Timebox: Wave 1, 3 h. Wave 2, 3 h.
