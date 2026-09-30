# Verify: feat/backend-api

Wave 1: every route in `contracts/API.md` runs in mock mode (`RIO_USE_MOCKS=1`).
Catalog, parser and forecast calls go to `backend/app/orders/mocks.py`, which serves
`contracts/fixtures/` plus a few extra illustrative SKUs. In mock mode orders live in
memory, so restarting the server clears them.

## Automated checks

```sh
cd backend
uv run ruff check . && uv run ruff format --check . && uv run pytest -q
```

- `tests/orders/`: pure, table-driven tests of the order rules. They cover quantity,
  completeness, legibility, triage thresholds, pricing, totals, the state machine, swap,
  review and queue order.
- `tests/api/`: every route through FastAPI's TestClient in mock mode, with no database.
  They cover uploads (magic bytes, 413, 400), the per-IP rate limit, 502 and 504 parser
  errors, a 500 with no stack trace, text orders, swap and undo, review, place, search and
  forecast.

## Manual walkthrough (mock mode)

Start the API:

```sh
cd backend
RIO_USE_MOCKS=1 uv run uvicorn app.main:app --port 8000
```

In another shell, save the script below as `verify.sh` and run
`API=http://localhost:8000 bash verify.sh`. It needs `curl` and `jq`. Each step prints
`<http status> <method> <path>` and then a summary of the body.

The expected statuses, in order, are 200, 200, 200, 200, 200, **409**, 200, **409**, 200,
200, 200, 200, 200, **400**. The order moves `pending_review` → `verified` → `placed`.

```bash
#!/usr/bin/env bash
# Walk the whole flow: sample order -> queue -> review with one edit -> verified -> place.
# Usage: API=http://localhost:8000 bash verify.sh   (needs curl and jq)
set -euo pipefail
API="${API:-http://localhost:8000}"

# call METHOD PATH [JSON]: prints "<status> <METHOD> <PATH>" and leaves the body in $BODY
call() {
  local method=$1 path=$2 data=${3:-}
  local out
  if [ -n "$data" ]; then
    out=$(curl -sS -w '\n%{http_code}' -X "$method" "$API$path" -H 'Content-Type: application/json' -d "$data")
  else
    out=$(curl -sS -w '\n%{http_code}' -X "$method" "$API$path")
  fi
  STATUS=$(tail -n1 <<<"$out")
  BODY=$(sed '$d' <<<"$out")
  echo "$STATUS $method $path"
}

echo "== 1. health"
call GET /api/health; echo "$BODY"

echo "== 2. sample order (no LLM call)"
call POST /api/orders/sample/typed_clinic_3
ORDER=$(jq -r .order_id <<<"$BODY")
jq -c '{order_id, status, total_inr, items: [.items[] | {item_id, sku: .sku.brand_name, packs: .quantity_packs, triage: .confidence.triage}]}' <<<"$BODY"

echo "== 3. customer polls the order"
call GET "/api/orders/$ORDER"; jq -c '{status}' <<<"$BODY"

echo "== 4. pharmacist queue"
call GET /api/queue; jq -c '[.[] | {order_id, worst_triage, counts}]' <<<"$BODY"

echo "== 5. pharmacist searches for the right SKU for the red line"
call GET "/api/catalog/search?q=paracetamol%20650&limit=3"; jq -c '[.[] | {sku_id: .sku.sku_id, score}]' <<<"$BODY"

echo "== 6. placing before review is refused"
call POST "/api/orders/$ORDER/place"; echo "$BODY"

echo "== 7. review: approve, with one edit (itm_3 -> Pacimol 650, 2 strips)"
call POST "/api/queue/$ORDER/review" \
  '{"decision":"approve","items":[{"item_id":"itm_3","action":"edit","sku_id":"sku_pacimol_650","quantity_packs":2}],"note":"Confirmed paracetamol 650 SOS"}'
jq -c '{status, total_inr, reviewed: (.reviewed_at != null), items: [.items[] | {item_id, sku: .sku.brand_name, packs: .quantity_packs, status}]}' <<<"$BODY"

echo "== 8. reviewing twice is refused"
call POST "/api/queue/$ORDER/review" '{"decision":"approve"}'; echo "$BODY"

echo "== 9. queue is empty again"
call GET /api/queue; echo "$BODY"

echo "== 10. customer places the verified order"
call POST "/api/orders/$ORDER/place"; jq -c '{status, total_inr}' <<<"$BODY"

echo "== 11. typed OTC order skips the queue; typed Rx asks for a prescription"
call POST /api/orders/text '{"text":"dolo and ORS"}'; jq -c '{status, total_inr}' <<<"$BODY"
call POST /api/orders/text '{"text":"augmentin"}'; jq -c '{status}' <<<"$BODY"

echo "== 12. photo upload path: re-upload a sample image as a prescription"
TMP=$(mktemp -t rio-rx.XXXXXX)
curl -sS -o "$TMP" "$API/api/samples/typed_clinic_3/image"
out=$(curl -sS -w '\n%{http_code}' -X POST "$API/api/orders/prescription" -F "image=@$TMP;type=image/png")
echo "$(tail -n1 <<<"$out") POST /api/orders/prescription"
sed '$d' <<<"$out" | jq -c '{source, status, has_image, lines: (.items | length)}'
out=$(curl -sS -w '\n%{http_code}' -X POST "$API/api/orders/prescription" -F "image=@$0;type=image/png")
echo "$(tail -n1 <<<"$out") POST /api/orders/prescription (a shell script pretending to be a png)"
sed '$d' <<<"$out"
rm -f "$TMP"
```

### Output (run on 2026-09-30 against the mock server)

```text
== 1. health
200 GET /api/health
{"ok":true,"mocks":true,"database":false}
== 2. sample order (no LLM call)
200 POST /api/orders/sample/typed_clinic_3
{"order_id":"ord_7428832555b4","status":"pending_review","total_inr":412.1,"items":[{"item_id":"itm_1","sku":"Augmentin 625 Duo","packs":1,"triage":"green"},{"item_id":"itm_2","sku":"Pan 40","packs":1,"triage":"amber"},{"item_id":"itm_3","sku":"Dolo 650","packs":1,"triage":"red"}]}
== 3. customer polls the order
200 GET /api/orders/ord_7428832555b4
{"status":"pending_review"}
== 4. pharmacist queue
200 GET /api/queue
[{"order_id":"ord_7428832555b4","worst_triage":"red","counts":{"green":1,"amber":1,"red":1}}]
== 5. pharmacist searches for the right SKU for the red line
200 GET /api/catalog/search?q=paracetamol%20650&limit=3
[{"sku_id":"sku_pacimol_650","score":0.95},{"sku_id":"sku_dolo_650","score":0.95},{"sku_id":"sku_crocin_500","score":0.8}]
== 6. placing before review is refused
409 POST /api/orders/ord_7428832555b4/place
{"error":{"code":"invalid_transition","message":"order is pending_review; cannot move to placed"}}
== 7. review: approve, with one edit (itm_3 -> Pacimol 650, 2 strips)
200 POST /api/queue/ord_7428832555b4/review
{"status":"verified","total_inr":434.5,"reviewed":true,"items":[{"item_id":"itm_1","sku":"Augmentin 625 Duo","packs":1,"status":"approved"},{"item_id":"itm_2","sku":"Pan 40","packs":1,"status":"approved"},{"item_id":"itm_3","sku":"Pacimol 650","packs":2,"status":"edited"}]}
== 8. reviewing twice is refused
409 POST /api/queue/ord_7428832555b4/review
{"error":{"code":"invalid_transition","message":"order is verified; cannot move to verified"}}
== 9. queue is empty again
200 GET /api/queue
[]
== 10. customer places the verified order
200 POST /api/orders/ord_7428832555b4/place
{"status":"placed","total_inr":434.5}
== 11. typed OTC order skips the queue; typed Rx asks for a prescription
200 POST /api/orders/text
{"status":"confirmed_otc","total_inr":55.6}
200 POST /api/orders/text
{"status":"needs_prescription"}
== 12. photo upload path: re-upload a sample image as a prescription
200 POST /api/orders/prescription
{"source":"prescription","status":"pending_review","has_image":true,"lines":3}
400 POST /api/orders/prescription (a shell script pretending to be a png)
{"error":{"code":"unsupported_image","message":"that file is not a readable jpeg, png or webp image"}}
```

What to notice:

- Step 2: the sample reproduces the fixture. Augmentin is green, Pan 40 is amber (duration
  unreadable) and Dolo is red (drug name unclear). The total is ₹412.10.
- Step 7: one edit swaps the red line to Pacimol 650 × 2. Items not listed are approved as
  they are, and the total is recomputed: 223.5 + 155 + 2 × 28 = ₹434.50.
- Steps 6 and 8: the state machine refuses out-of-order moves with 409 `invalid_transition`.

## Docker image (mock mode)

```sh
docker build -f deploy/Dockerfile -t rio-api:test .
docker run --rm -d -p 127.0.0.1:18000:8000 -e RIO_USE_MOCKS=1 --name rio-api-test rio-api:test
curl -s http://127.0.0.1:18000/api/health     # {"ok":true,"mocks":true,"database":false}
curl -s -X POST http://127.0.0.1:18000/api/orders/sample/typed_clinic_3 | jq -c '{status,total_inr}'
                                              # {"status":"pending_review","total_inr":412.1}
docker exec rio-api-test id                   # uid=999(rio): not root
docker stop rio-api-test
```

These checks passed locally on 2026-09-30.

## Live mode (Wave 2, not run yet)

After Wave 2 is deployed, run the same script against production:

```sh
API=https://rio-api.buildspacelabs.com bash verify.sh
```

The expected statuses are the same, with these differences:

- `/api/health` reports `"mocks": false, "database": true`.
- SKUs, scores and prices come from the real catalog. In step 7, replace `sku_pacimol_650`
  with a real `sku_id` from the step 5 search.
- Step 12 calls the vision model, takes 5–30 s, and counts against the 10-per-hour limit.

## Notes for the frontend

- **Swap:** after `POST /api/orders/{id}/swap` with `use_generic: true`, the item's `sku`
  and `generic_alternative` are the same generic SKU, and `savings_inr` is what the
  customer saves. So "generic taken" means `item.sku.sku_id === item.generic_alternative?.sku_id`.
  `use_generic: false` restores the brand. Swaps are allowed while the order is
  `pending_review` or `confirmed_otc`.
- **Typed orders:** on a `confirmed_otc` order, phrases that match nothing stay on the
  order with `sku: null` and status `removed`. If nothing matches at all, the API answers
  422 `invalid_request`.
- **Review:** approving an order that still has an item with no SKU returns 422
  `invalid_request`. The pharmacist must edit or remove that item first.
