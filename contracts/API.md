# HTTP API

Base URL: `https://rio-api.buildspacelabs.com` in production, `http://localhost:8000` locally.
All bodies are JSON unless stated. Types are the models in `backend/app/contracts.py`
(TypeScript: `frontend/src/contracts.gen.ts`). Mock payloads are in `contracts/fixtures/`.

Every error is `ErrorResponse`: `{"error": {"code": "...", "message": "..."}}`.

## Orders (customer side)

| Method | Path | Body | Returns | Notes |
|---|---|---|---|---|
| POST | `/api/orders/prescription` | multipart: `image` (jpeg/png/webp, ≤ 5 MB) | `Order` | Synchronous: parse + match, 5–30 s. Status is `pending_review`. Rate limited per IP. |
| POST | `/api/orders/sample/{sample_id}` | — | `Order` | Same flow with a cached parse; no LLM call, no rate limit. The demo fallback. |
| POST | `/api/orders/text` | `TextOrderRequest` | `Order` | `confirmed_otc` if every item is OTC, `needs_prescription` if any is Rx-only. |
| GET | `/api/orders/{order_id}` | — | `Order` | The chat polls this every 2 s while `pending_review`. |
| GET | `/api/orders/{order_id}/image` | — | image bytes | 404 when `has_image` is false. |
| POST | `/api/orders/{order_id}/swap` | `SwapRequest` | `Order` | Customer takes or undoes the generic alternative. Only before review. |
| POST | `/api/orders/{order_id}/place` | — | `Order` | Stub: `verified` or `confirmed_otc` → `placed`. |
| GET | `/api/samples` | — | `list[Sample]` | |
| GET | `/api/samples/{sample_id}/image` | — | image bytes | |

## Pharmacist

| Method | Path | Body | Returns | Notes |
|---|---|---|---|---|
| GET | `/api/queue` | — | `list[QueueItem]` | Only `pending_review`. Worst triage first, then oldest. |
| POST | `/api/queue/{order_id}/review` | `ReviewRequest` | `Order` | `approve` → `verified`; `reject` → `rejected`. Items not listed are approved as is. |
| GET | `/api/catalog/search?q=&limit=` | — | `list[MatchCandidate]` | For the pharmacist's "change SKU" picker. `limit` ≤ 20. |

## Forecast

| Method | Path | Body | Returns | Notes |
|---|---|---|---|---|
| GET | `/api/forecast/summary` | — | `ForecastSummary` | 404 `no_forecast` before the first run. |
| GET | `/api/forecast/sku/{sku_id}?area=` | — | `SkuForecast` | |

## Visitors

| Method | Path | Body | Returns | Notes |
|---|---|---|---|---|
| POST | `/api/visitors` | `VisitorRequest` | 204, no body | The email wall. Format check only (`x@y.z`), stored lowercased in `visitors`; a repeat visit bumps `last_seen` and `visits`. 422 `invalid_request` for a malformed email. |

## Health

| Method | Path | Returns |
|---|---|---|
| GET | `/api/health` | `{"ok": true, "mocks": bool, "database": bool}` |

## Error codes

| Status | `code` | When |
|---|---|---|
| 400 | `unsupported_image` | Not jpeg/png/webp, or unreadable |
| 404 | `not_found` | Unknown order, sample or SKU |
| 404 | `no_forecast` | Forecast has never run |
| 409 | `invalid_transition` | e.g. reviewing an order that is not `pending_review` |
| 413 | `image_too_large` | Over `MAX_UPLOAD_MB` |
| 422 | `invalid_request` | Body failed validation, approving an item with no SKU, swapping an item with no generic, or a text order where nothing matches |
| 429 | `rate_limited` | Over `PARSE_RATE_LIMIT_PER_HOUR` for this IP; message says when to retry |
| 502 | `parser_failed` | The vision model errored or returned junk; the UI offers a sample instead |
| 504 | `parser_timeout` | The vision model exceeded `OPENROUTER_TIMEOUT_S` |

## Order rules the backend enforces

- A prescription or sample order is always `pending_review`: every prescription order gets
  a pharmacist check. Confidence only sets each item's triage.
- Triage: **red** if there's no SKU, the drug is illegible, or the match score is < 0.6.
  **Amber** if the match score is < 0.85, completeness is < 1 or any field is illegible.
  **Green** otherwise. `reasons` explains every amber and red.
- `quantity_packs` = ceil(quantity / pack_size) when the Rx states an explicit `quantity`;
  otherwise ceil(doses_per_day × duration_days / pack_size); otherwise 1 pack, with a
  reason on the item. For text orders, a count the customer writes ("2 strips of crocin")
  is taken as packs.
- Completeness counts drug, strength, frequency and duration. A written `quantity`
  stands in for duration.
- Items with status `removed` don't count toward `total_inr`.
- Swap: `use_generic: true` sets `sku` to the generic, so `sku == generic_alternative`,
  and `savings_inr` keeps showing the saving. `use_generic: false` restores the brand.
  Repeating the same swap changes nothing. Allowed in `pending_review` and
  `confirmed_otc`, otherwise 409 `invalid_transition`; an item with no generic is 422.
- Approving an item with no SKU, or a text order where nothing matches, is 422
  `invalid_request` with a message saying which item or phrase failed.
