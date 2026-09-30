# Verify: `feat/frontend` (Wave 1, mock API)

## Run it

```bash
cd frontend
npm install
VITE_MOCKS=1 npm run dev          # http://localhost:5173, in-browser mock API
npm test                          # vitest: 54 tests (mock state machine, money, review helpers, resize)
npm run build                     # tsc + vite build
npm run gen:contracts -- --check  # contracts.gen.ts is current
```

Without `VITE_MOCKS=1` the client calls `VITE_API_BASE_URL` (default `http://localhost:8000`).

About the mock:
- It is seeded from `contracts/fixtures/` and keeps real state: prescription and sample orders go to
  `pending_review` after 2 s of fake parse latency; review → `verified` or `rejected`; typed orders →
  `confirmed_otc` or `needs_prescription`; swap and place follow the rules in `contracts/API.md`
  (409 on invalid transitions).
- State lives in `localStorage` (`rio.mock.v1`), so `/chat` and `/pharmacist` in two tabs share orders.
  **Reset demo** (top right) clears it back to the seeded queue, so each Loom take starts clean.
- To rehearse failures, add `?fail=parser_failed`, `?fail=parser_timeout` or `?fail=rate_limited` to
  the URL. The next photo upload then fails with 502, 504 or 429 and the chat offers "Try a sample".
- In mocks, any uploaded photo parses as the 3-line Sunrise Clinic prescription. The console
  shows the photo you uploaded.

## Routes

| Route | What |
|---|---|
| `/` | Demo mode: phone-framed chat on the left, pharmacist console on the right, one shared state. Below 900 px they become Customer and Pharmacist tabs. |
| `/chat` | Customer chat on its own; full screen at 390 px. |
| `/pharmacist` | Queue plus order review. |
| `/forecast` | Backtest headline, SKU and area picker, actual vs forecast chart with a "now" line, reorder table. |

## Loom script, click by click (on `/`, 1440×900 or larger)

0. Click **Reset demo**. The queue already holds two orders so it looks lived-in.
1. **0–10 s.** Open on `/`, with the greeting and quick replies on the phone.
2. **10–40 s.** On the phone, click **📷 Upload prescription** and pick a photo. Or click **Try a sample**
   → **Typed clinic Rx, 3 lines**. You'll see "Reading your prescription…" with typing dots for about 2 s,
   then the cart card (Augmentin, Pan 40, Dolo 650, total ₹412.10) with a **Save ₹42.50 — switch to
   generic** chip and "A pharmacist is verifying your order." Click the chip: Augmentin becomes
   Moxclav 625 and the total drops to ₹369.60. On the right, the new order arrives in the queue marked
   **New** and opens on its own, with lines grouped **Fix before approving** (red ✕), **Check these**
   (amber !) and **Read cleanly** (green ✓).
3. **40–60 s.** On the red line 3 ("Tab D?lo 650 SOS"), click **✎ Edit**. The SKU picker opens,
   pre-searched with "Dolo 650". Pick a SKU, set the packs, then click **Use this SKU**. Click **✓ Approve
   all green**, then **Approve order**. Approve stays disabled until the red line has a decision. Within
   2 s the phone shows the **Verified by pharmacist** stamp, the final cart with changed lines struck
   through (or "Confirmed by the pharmacist"), and **Place order · ₹…**. Click it.
4. **60–75 s.** The accuracy table lives in the README, not this UI.
5. **75–90 s.** Click **Forecast**. It opens on Dolo 650 in Area A: the actual line spikes just before
   "now", the forecast picks up the higher level, and the reorder table's first row is red
   **Stockout risk** with hours to stockout and a reorder quantity. Click any row to chart it.

Other paths:
- Type `dolo, ORS` in the chat to get an OTC cart and **Place order** straight away.
- Type `augmentin` to get "Augmentin 625 Duo needs a prescription. Upload one?"
- In the console, **Reject with note** requires a note, and the chat then shows it.

## Screenshots

Captured with Playwright against `VITE_MOCKS=1` (script walks the path above).

| | |
|---|---|
| Split screen, cart and queue | ![](feat-frontend/03-demo-cart-and-queue.png) |
| Pharmacist editing the red line | ![](feat-frontend/04-pharmacist-edit.png) |
| Verified: chat turns green | ![](feat-frontend/05-demo-verified.png) |
| Forecast tab | ![](feat-frontend/06-forecast.png) |
| `/chat` at 390 px | ![](feat-frontend/07-mobile-chat.png) |
| Demo at 390 px, Pharmacist tab | ![](feat-frontend/08-mobile-demo-pharmacist.png) |
| Typed OTC, Rx needed, parser failure → Try a sample | ![](feat-frontend/09-mobile-text-and-failure.png) |

## Design notes

- The tokens match `docs/explainer.html`: calm teal `#0a6b58`, cool paper, Bricolage Grotesque for
  headings, Source Sans 3 for body text, JetBrains Mono only for prescription lines as written.
- Triage never relies on colour alone. Each level has its own shape, glyph and word: green circle ✓
  "Clear", amber triangle ! "Check", red square ✕ "Fix".
- Prices use tabular numerals and `formatINR` (`₹1,234.50`, Indian grouping, always two decimals).
- The only flourish is the pharmacist's stamp.

## Wave 2 notes

- Point `VITE_API_BASE_URL` at the local API, then `https://rio-api.buildspacelabs.com`, and build
  without `VITE_MOCKS`.
- The chat uses `api.sampleImageUrl()` / `api.orderImageUrl()` rather than `Sample.thumbnail_url`,
  so relative URLs resolve against the API base.
- Detecting a swap assumes that after `swap(use_generic: true)` the backend sets `sku` to the generic
  and keeps `generic_alternative`, as the mock does. Check this against the real API.
- Check against real data: long brand names, `sku: null` lines (the console forces edit or remove),
  0 parsed lines, and 5–30 s parses (the typing bubble has no timeout).
