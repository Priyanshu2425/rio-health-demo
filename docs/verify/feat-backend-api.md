# Verify: feat/backend-api

The API serves every route in `contracts/API.md` in two modes:

- **Real mode** (`RIO_USE_MOCKS=0`, production). It reads only Neon: catalog, samples,
  forecast and orders. Startup fails if `RIO_HEALTH_DATABASE_URL` is missing or the
  database is unreachable; there is no in-memory fallback. If `forecast_runs` is empty,
  the first forecast runs in a background task (about 17 s) without blocking requests.
- **Mock mode** (`RIO_USE_MOCKS=1`, development only). Catalog, parser and forecast calls
  go to `backend/app/orders/mocks.py`, which serves `contracts/fixtures/`, and orders live
  in memory. A restart clears them.

## Start the API locally

From the repo root, with the shared `.env` in place (it provides the database URL,
OpenRouter key and model ids):

```sh
cd backend
RIO_USE_MOCKS=0 uv run uvicorn app.main:app --port 8000   # real mode, against Neon
RIO_USE_MOCKS=1 uv run uvicorn app.main:app --port 8000   # mock mode, no database
```

`GET /api/health` answers `{"ok":true,"mocks":false,"database":true}` in real mode and
`{"ok":true,"mocks":true,"database":false}` in mock mode. Point the frontend at it with
`VITE_API_BASE_URL=http://localhost:8000`.

## Automated checks

```sh
cd backend
uv run ruff check . && uv run ruff format --check . && uv run pytest -q
```

- `tests/orders/test_rules.py`: pure, table-driven tests of the order rules. They cover
  quantity (units, typed counts), completeness, legibility, triage thresholds and reasons,
  pricing, totals, the state machine, swap, review and queue order.
- `tests/orders/test_repo_db.py` (marked `db`): the Postgres order repo against Neon.
  It covers the round trip, images, swaps kept across saves, the stale-status guard and
  pending order. Its orders use ids starting `ord_test_<run>` and are deleted afterwards;
  no other table is touched. It skips without `RIO_HEALTH_DATABASE_URL`.
- `tests/api/`: every route through FastAPI's TestClient in mock mode, with no database.
  They cover uploads (magic bytes, decode check, 413, 400 before the rate limit counts),
  the per-IP rate limit, 502 and 504 parser errors, a 500 with no stack trace, text
  orders, swap and undo, review, place, search and forecast. They also cover startup:
  real mode without a DB URL fails, there is no memory fallback, and the forecast
  bootstrap runs only on an empty table.

## Walkthrough script

The same script runs in both modes. Save it as `verify.sh` and run
`API=http://localhost:8000 bash verify.sh`; it needs `curl` and `jq`. `UPLOAD=1` adds
step 14, one real photo upload. In real mode that is one vision call, about $0.01, and
it counts against the 10-per-hour limit.

Expected statuses, in order: 200 (health), 200 (samples), 200 (sample order), 200 (poll),
200 (queue), 200 (search), **409** (place before review), 200 (review), **409** (review
again), 200 (queue), 200 (place), 200 and 200 (typed orders), **400** (broken image), and
with `UPLOAD=1` a final 200. The order moves `pending_review` → `verified` → `placed`.

```bash
#!/usr/bin/env bash
# Walk the whole flow: sample order -> queue -> review with one edit -> verified -> place.
# Works in mock and real mode. Usage: API=http://localhost:8000 bash verify.sh
# Needs curl and jq. UPLOAD=1 adds one real photo upload (in real mode: one vision call, ~$0.01).
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

echo "== 2. samples"
call GET /api/samples; jq -c '[.[].sample_id]' <<<"$BODY"

echo "== 3. sample order (cached parse, no vision call)"
call POST /api/orders/sample/typed_clinic_3
ORDER=$(jq -r .order_id <<<"$BODY")
CURRENT=$(jq -r '.items[2].sku.sku_id' <<<"$BODY")
jq -c '{status, total_inr, items: [.items[] | {item_id, sku: .sku.brand_name, packs: .quantity_packs, triage: .confidence.triage}]}' <<<"$BODY"

echo "== 4. customer polls the order"
call GET "/api/orders/$ORDER"; jq -c '{status}' <<<"$BODY"

echo "== 5. pharmacist queue (this order's row)"
call GET /api/queue; jq -c --arg o "$ORDER" '[.[] | select(.order_id == $o) | {worst_triage, counts, total_inr}]' <<<"$BODY"

echo "== 6. pharmacist searches for another SKU for itm_3"
call GET "/api/catalog/search?q=paracetamol%20650&limit=5"
jq -c '[.[] | {sku_id: .sku.sku_id, brand: .sku.brand_name, mrp: .sku.mrp_inr, score}]' <<<"$BODY"
EDIT_SKU=$(jq -r --arg cur "$CURRENT" '[.[] | select(.sku.sku_id != $cur)][0].sku.sku_id' <<<"$BODY")
echo "edit itm_3: $CURRENT -> $EDIT_SKU"

echo "== 7. placing before review is refused"
call POST "/api/orders/$ORDER/place"; echo "$BODY"

echo "== 8. review: approve, with one edit (itm_3 -> $EDIT_SKU, 2 packs)"
call POST "/api/queue/$ORDER/review" \
  "{\"decision\":\"approve\",\"items\":[{\"item_id\":\"itm_3\",\"action\":\"edit\",\"sku_id\":\"$EDIT_SKU\",\"quantity_packs\":2}],\"note\":\"Swapped to the equivalent in stock\"}"
jq -c '{status, total_inr, reviewed: (.reviewed_at != null), items: [.items[] | {item_id, sku: .sku.brand_name, packs: .quantity_packs, line: .line_total_inr, status}]}' <<<"$BODY"

echo "== 9. reviewing twice is refused"
call POST "/api/queue/$ORDER/review" '{"decision":"approve"}'; echo "$BODY"

echo "== 10. order has left the queue"
call GET /api/queue; jq -c --arg o "$ORDER" '[.[] | select(.order_id == $o)] | length' <<<"$BODY"

echo "== 11. customer places the verified order"
call POST "/api/orders/$ORDER/place"; jq -c '{status, total_inr}' <<<"$BODY"

echo "== 12. typed OTC order skips the queue; typed Rx asks for a prescription"
call POST /api/orders/text '{"text":"dolo and ORS"}'
jq -c '{status, total_inr, items: [.items[] | {requested_text, sku: .sku.brand_name, rx_only: .sku.rx_only}]}' <<<"$BODY"
call POST /api/orders/text '{"text":"augmentin"}'
jq -c '{status, items: [.items[] | {requested_text, sku: .sku.brand_name, rx_only: .sku.rx_only}]}' <<<"$BODY"

echo "== 13. a JPEG header on bytes Pillow cannot decode is refused before any vision call"
TMP=$(mktemp -t rio-rx.XXXXXX)
printf '\xff\xd8\xff\xe0 truncated jpeg' > "$TMP"
out=$(curl -sS -w '\n%{http_code}' -X POST "$API/api/orders/prescription" -F "image=@$TMP;type=image/jpeg")
echo "$(tail -n1 <<<"$out") POST /api/orders/prescription"
sed '$d' <<<"$out"

if [ "${UPLOAD:-0}" = 1 ]; then
  echo "== 14. real photo upload: the typed_clinic_3 sample image as a prescription"
  curl -sS -o "$TMP" "$API/api/samples/typed_clinic_3/image"
  start=$(date +%s)
  out=$(curl -sS -w '\n%{http_code}' -X POST "$API/api/orders/prescription" -F "image=@$TMP;type=image/jpeg")
  echo "$(tail -n1 <<<"$out") POST /api/orders/prescription ($(( $(date +%s) - start )) s)"
  sed '$d' <<<"$out" | jq -c '{source, status, has_image, model: .parsed_rx.model, latency_ms: .parsed_rx.latency_ms, cost_usd: .parsed_rx.cost_usd, items: [.items[] | {sku: .sku.brand_name, packs: .quantity_packs, triage: .confidence.triage}]}'
fi
rm -f "$TMP"
```

## Real mode output (local API against Neon, 2026-09-30)

Steps 1–13 are from the final code. Step 14 is from the one real upload made for this
branch, an earlier run of the same script (`UPLOAD=1`) a few commits back; the code it
exercises (parse, match, cart, store) did not change after it. Its cost: $0.0065.

```text
== 1. health
200 GET /api/health
{"ok":true,"mocks":false,"database":true}
== 2. samples
200 GET /api/samples
["typed_clinic_3","hospital_opd_4","handwritten_style_3"]
== 3. sample order (cached parse, no vision call)
200 POST /api/orders/sample/typed_clinic_3
{"status":"pending_review","total_inr":412.69,"items":[{"item_id":"itm_1","sku":"Augmentin 625 Duo","packs":1,"triage":"green"},{"item_id":"itm_2","sku":"Pan 40","packs":1,"triage":"green"},{"item_id":"itm_3","sku":"Dolo 650","packs":1,"triage":"green"}]}
== 4. customer polls the order
200 GET /api/orders/ord_561eb602783d
{"status":"pending_review"}
== 5. pharmacist queue (this order's row)
200 GET /api/queue
[{"worst_triage":"green","counts":{"green":3,"amber":0,"red":0},"total_inr":412.69}]
== 6. pharmacist searches for another SKU for itm_3
200 GET /api/catalog/search?q=paracetamol%20650&limit=5
[{"sku_id":"sku_crocin_650","brand":"Crocin 650","mrp":33.0,"score":0.8635},{"sku_id":"sku_dolo_650","brand":"Dolo 650","mrp":34.27,"score":0.8635},{"sku_id":"sku_xykaa_rapid_650","brand":"Xykaa Rapid 650","mrp":20.59,"score":0.8635},{"sku_id":"sku_lanol_er","brand":"Lanol ER","mrp":21.75,"score":0.8635},{"sku_id":"sku_calpol_650mg","brand":"Calpol 650mg","mrp":34.23,"score":0.8635}]
edit itm_3: sku_dolo_650 -> sku_crocin_650
== 7. placing before review is refused
409 POST /api/orders/ord_561eb602783d/place
{"error":{"code":"invalid_transition","message":"A pharmacist is still checking this order. You can place it once it's verified."}}
== 8. review: approve, with one edit (itm_3 -> sku_crocin_650, 2 packs)
200 POST /api/queue/ord_561eb602783d/review
{"status":"verified","total_inr":444.42,"reviewed":true,"items":[{"item_id":"itm_1","sku":"Augmentin 625 Duo","packs":1,"line":223.42,"status":"approved"},{"item_id":"itm_2","sku":"Pan 40","packs":1,"line":155.0,"status":"approved"},{"item_id":"itm_3","sku":"Crocin 650","packs":2,"line":66.0,"status":"edited"}]}
== 9. reviewing twice is refused
409 POST /api/queue/ord_561eb602783d/review
{"error":{"code":"invalid_transition","message":"This order was already reviewed, so it can't be changed now."}}
== 10. order has left the queue
200 GET /api/queue
0
== 11. customer places the verified order
200 POST /api/orders/ord_561eb602783d/place
{"status":"placed","total_inr":444.42}
== 12. typed OTC order skips the queue; typed Rx asks for a prescription
200 POST /api/orders/text
{"status":"confirmed_otc","total_inr":52.07,"items":[{"requested_text":"dolo","sku":"Dolo","rx_only":false},{"requested_text":"ORS","sku":"Electral Powder","rx_only":false}]}
200 POST /api/orders/text
{"status":"needs_prescription","items":[{"requested_text":"augmentin","sku":"Augmentin 625 Duo","rx_only":true}]}
== 13. a JPEG header on bytes Pillow cannot decode is refused before any vision call
400 POST /api/orders/prescription
{"error":{"code":"unsupported_image","message":"We couldn't open that image. Please take a new photo of the prescription and try again."}}
== 14. real photo upload: the typed_clinic_3 sample image as a prescription
200 POST /api/orders/prescription (10 s)
{"source":"prescription","status":"pending_review","has_image":true,"model":"google/gemini-3.8-flash","latency_ms":9438,"cost_usd":0.00651075,"items":[{"sku":"Augmentin 625 Duo","packs":1,"triage":"green"},{"sku":"Pan 40","packs":1,"triage":"green"},{"sku":"Dolo 650","packs":1,"triage":"green"}]}
```

What to notice:

- Step 3: the real `typed_clinic_3` sample is a clean typed Rx, so all three lines are
  green. For amber lines in the pharmacist console, use `hospital_opd_4`. Its Montair LC
  and Pan-D lines have no strength written, so they come back amber with the reason
  "strength not written".
- Step 8: one edit swaps itm_3 to Crocin 650 × 2. Unlisted items are approved as they are,
  and the total is recomputed: 223.42 + 155 + 2 × 33 = ₹444.42.
- Step 14: the vision parse of the sample photo matches its cached parse, giving the same
  three SKUs, in 9.4 s for $0.0065.

The other real samples, from the same session (`POST /api/orders/sample/{id}`, 2–4 s each
with no vision call):

```text
hospital_opd_4 -> 200: Azithral 500 (green), Montair-LC (amber), Pan-D (amber), Calpol 500mg (green); ₹684.01
handwritten_style_3 -> 200: Telma 40 (green), Glycomet 500 SR (green), Atorva × 2 (green); ₹498.28
text "two strips of crocin, cetirizine" -> 200 confirmed_otc: Crocin 650 × 2, Wincet × 1
text "flubberwort" -> 422 invalid_request: "We couldn't find “flubberwort” in our catalog. Try the brand name printed on the strip."
```

## Mock mode output (2026-09-30)

```text
== 1. health
200 GET /api/health
{"ok":true,"mocks":true,"database":false}
== 2. samples
200 GET /api/samples
["typed_clinic_3","handwritten_2"]
== 3. sample order (cached parse, no vision call)
200 POST /api/orders/sample/typed_clinic_3
{"status":"pending_review","total_inr":412.1,"items":[{"item_id":"itm_1","sku":"Augmentin 625 Duo","packs":1,"triage":"green"},{"item_id":"itm_2","sku":"Pan 40","packs":1,"triage":"amber"},{"item_id":"itm_3","sku":"Dolo 650","packs":1,"triage":"red"}]}
== 4. customer polls the order
200 GET /api/orders/ord_7bd23abb7b9e
{"status":"pending_review"}
== 5. pharmacist queue (this order's row)
200 GET /api/queue
[{"worst_triage":"red","counts":{"green":1,"amber":1,"red":1},"total_inr":412.1}]
== 6. pharmacist searches for another SKU for itm_3
200 GET /api/catalog/search?q=paracetamol%20650&limit=5
[{"sku_id":"sku_pacimol_650","brand":"Pacimol 650","mrp":28.0,"score":0.95},{"sku_id":"sku_dolo_650","brand":"Dolo 650","mrp":33.6,"score":0.95},{"sku_id":"sku_crocin_500","brand":"Crocin Advance 500","mrp":24.5,"score":0.8},{"sku_id":"sku_okacet_10","brand":"Okacet 10","mrp":18.0,"score":0.57},{"sku_id":"sku_pan_40","brand":"Pan 40","mrp":155.0,"score":0.57}]
edit itm_3: sku_dolo_650 -> sku_pacimol_650
== 7. placing before review is refused
409 POST /api/orders/ord_7bd23abb7b9e/place
{"error":{"code":"invalid_transition","message":"A pharmacist is still checking this order. You can place it once it's verified."}}
== 8. review: approve, with one edit (itm_3 -> sku_pacimol_650, 2 packs)
200 POST /api/queue/ord_7bd23abb7b9e/review
{"status":"verified","total_inr":434.5,"reviewed":true,"items":[{"item_id":"itm_1","sku":"Augmentin 625 Duo","packs":1,"line":223.5,"status":"approved"},{"item_id":"itm_2","sku":"Pan 40","packs":1,"line":155.0,"status":"approved"},{"item_id":"itm_3","sku":"Pacimol 650","packs":2,"line":56.0,"status":"edited"}]}
== 9. reviewing twice is refused
409 POST /api/queue/ord_7bd23abb7b9e/review
{"error":{"code":"invalid_transition","message":"This order was already reviewed, so it can't be changed now."}}
== 10. order has left the queue
200 GET /api/queue
0
== 11. customer places the verified order
200 POST /api/orders/ord_7bd23abb7b9e/place
{"status":"placed","total_inr":434.5}
== 12. typed OTC order skips the queue; typed Rx asks for a prescription
200 POST /api/orders/text
{"status":"confirmed_otc","total_inr":55.6,"items":[{"requested_text":"dolo","sku":"Dolo 650","rx_only":false},{"requested_text":"ORS","sku":"Electral Powder","rx_only":false}]}
200 POST /api/orders/text
{"status":"needs_prescription","items":[{"requested_text":"augmentin","sku":"Augmentin 625 Duo","rx_only":true}]}
== 13. a JPEG header on bytes Pillow cannot decode is refused before any vision call
400 POST /api/orders/prescription
{"error":{"code":"unsupported_image","message":"We couldn't open that image. Please take a new photo of the prescription and try again."}}
```

## Docker image

The image holds `backend/` only; at runtime the app reads only the database. So check it
in real mode with the local `.env`. The container gets the DB URL from `--env-file`, and
nothing from the repo is baked in.

```sh
docker build -f deploy/Dockerfile -t rio-api:test .
docker run --rm -d -p 127.0.0.1:18000:8000 --env-file .env -e RIO_USE_MOCKS=0 --name rio-api-test rio-api:test
curl -s http://127.0.0.1:18000/api/health
curl -s -X POST http://127.0.0.1:18000/api/orders/sample/typed_clinic_3 | jq -c '{status,total_inr}'
docker exec rio-api-test id
docker stop rio-api-test
docker run --rm -e RIO_USE_MOCKS=0 rio-api:test    # no DB URL: must refuse to start
```

Results on 2026-09-30:

```text
{"ok":true,"mocks":false,"database":true}
{"status":"pending_review","total_inr":412.69}
hospital_opd_4: Azithral 500 green; Montair-LC amber ["strength not written"]; Pan-D amber ["strength not written"]; Calpol 500mg green
uid=999(rio) gid=999(rio) groups=999(rio)          # non-root
ls /app -> backend                                  # no data/, no contracts/
health status: healthy
RuntimeError: RIO_USE_MOCKS=0 needs RIO_HEALTH_DATABASE_URL. Set it, or set RIO_USE_MOCKS=1 for local development against fixtures.
ERROR:    Application startup failed. Exiting.
```

The first request can get an empty reply while startup is still opening the Neon pool
(a few seconds). The compose healthcheck's 10 s start period covers that.

## Live (not deployed yet)

The EC2 host and tunnel are not set up yet; `deploy/README.md` has the owner's steps.
After the first deploy, run `API=https://rio-api.buildspacelabs.com bash verify.sh` and
expect the real-mode statuses above.

## Notes for the frontend

- **Error messages:** every `error.message` is one or two plain sentences meant for the
  person on screen, and safe to show verbatim. The wording lives in
  `backend/app/orders/messages.py`. Branch on `error.code`, never on the wording. The
  only number in a 429 message is the retry time in minutes ("try again in 12 minutes").

- **Swap:** after `POST /api/orders/{id}/swap` with `use_generic: true`, the item's `sku`
  and `generic_alternative` are the same generic SKU, and `savings_inr` is what the
  customer saves. So "generic taken" means `item.sku.sku_id === item.generic_alternative?.sku_id`.
  `use_generic: false` restores the brand.
- **Typed orders:** on a `confirmed_otc` order, phrases that match nothing stay on the
  order with `sku: null` and status `removed`. If nothing matches at all, the API answers
  422 `invalid_request`.
- **Review:** approving an order that still has an item with no SKU returns 422
  `invalid_request`. The pharmacist must edit or remove that item first.
- **Samples:** mock mode has `typed_clinic_3` and `handwritten_2`; real mode has
  `typed_clinic_3`, `hospital_opd_4` and `handwritten_style_3`. Read the list from
  `GET /api/samples` rather than hard-coding ids.
