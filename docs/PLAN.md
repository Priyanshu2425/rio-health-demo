# Build plan

## Branches and ownership

| Branch | Brief | Owns (may edit) |
|---|---|---|
| `feat/data-forecast` | [01](briefs/01-data-forecast.md) | `backend/app/catalog/`, `backend/app/forecast/`, `scripts/etl/`, `data/`, `backend/tests/catalog/`, `backend/tests/forecast/` |
| `feat/parser-eval` | [02](briefs/02-parser-eval.md) | `backend/app/parser/`, `eval/`, `backend/tests/parser/` |
| `feat/backend-api` | [03](briefs/03-backend-api.md) | `backend/app/api/`, `backend/app/orders/`, `backend/app/main.py` (routes and middleware only), `deploy/`, `backend/tests/api/`, `backend/tests/orders/` |
| `feat/frontend` | [04](briefs/04-frontend.md) | `frontend/` except `src/contracts.gen.ts` |

Everything in `contracts/README.md` is frozen. Each branch also writes its own
`VERIFY.md` at `docs/verify/<branch-name>.md`, so the branches can't conflict.

## Timeline

| Hours | What | Who |
|---|---|---|
| H0–H1 | Account setup ([00](briefs/00-you-setup.md)); review and push `main` | You |
| H1–H4 | **Wave 1:** all four branches in parallel. Backend and frontend run on fixtures (`RIO_USE_MOCKS=1`). | Agents |
| H2 | **Checkpoint:** any contract change requests? Land them as `chore/contracts-v2`. | You |
| H4 | **Gate:** merge `feat/data-forecast`, then `feat/parser-eval` (SKU match ≥ 80% on synthetic). | You |
| H4–H7 | **Wave 2:** backend rebases and replaces mocks with the real modules and deploys to EC2. Frontend rebases and points at the live API. | Agents |
| H7 | **Gate:** the full flow works on `rio.buildspacelabs.com`. Merge `feat/backend-api`, then `feat/frontend`. | You |
| H7–H8 | End-to-end run, fix the top 3 bugs, freeze features | You + agents |
| H8–H9 | README: architecture diagram, accuracy table, "what I'd build next" | Agent |
| H9–H10 | Record the Loom, send the email | You |

## Merge order

`main` (contracts) → `feat/data-forecast` → `feat/parser-eval` → `feat/backend-api` → `feat/frontend`

## Cut order when late

1. The generic-swap chip in the chat. Keep the data.
2. The reorder table. Keep the forecast chart.
3. The whole forecast tab.

Never cut: photo → cart → pharmacist review → verified.

## Loom script (90 s)

1. **0–10 s:** "Rio takes medicine orders on WhatsApp. Here's the part that's hard: reading prescriptions safely."
2. **10–40 s:** Upload a handwritten prescription → cart appears with a generic-swap chip → the right pane lights up with green, amber and red lines.
3. **40–60 s:** The pharmacist fixes the red line with the SKU picker and approves → the chat turns green with "Verified by pharmacist."
4. **60–75 s:** Accuracy table: synthetic vs handwritten, model comparison, "% of lines approved unedited."
5. **75–90 s:** Forecast tab: the spike is caught, stockout alert, reorder suggestion. "Next: WhatsApp Cloud API, auth, payments."
