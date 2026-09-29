# 04: Frontend (`feat/frontend`)

Read first: `docs/DECISIONS.md`, `docs/PLAN.md` (the Loom script), `contracts/API.md`,
`frontend/src/contracts.gen.ts`, `contracts/fixtures/`.

## You own

`frontend/` except `src/contracts.gen.ts`, plus `docs/verify/feat-frontend.md`. You may
add npm dependencies. Touch nothing outside `frontend/`.

## Wave 1 (H1–H4): the whole UI on fixtures

1. **API client** (`src/api.ts`): one function per route in `contracts/API.md`, typed with
   `contracts.gen.ts`, with the base URL from `VITE_API_BASE_URL`. `VITE_MOCKS=1` swaps in
   an in-browser mock that serves `../contracts/fixtures/` and simulates the flow: create
   → `pending_review`, review → `verified`, 2 s of fake parse latency. Errors surface
   `ErrorResponse.error.message`.
2. **Routes:**
   - `/`: **demo mode**. Split screen: a phone-framed chat on the left, the pharmacist
     console on the right. Below 900 px it stacks, or shows tabs.
   - `/chat`, `/pharmacist`, `/forecast`: each one on its own, and mobile-first.
3. **Chat (WhatsApp-like, not a WhatsApp clone):** a Rio-branded header, a greeting
   bubble and quick replies ("📷 Upload prescription", "Try a sample", "Type medicines").
   - **Photo:** resize client-side to ≤ 1600 px, JPEG, before upload. Then "Reading your
     prescription…" with typing dots, then a **cart card** bubble with lines, pack
     labels, prices, total, a "Save ₹X — switch to generic" chip per line (calls `swap`),
     and a status line: "A pharmacist is verifying your order."
   - Poll `GET /api/orders/{id}` every 2 s while `pending_review`. On `verified`, show a
     "✅ Verified by pharmacist" bubble with the final cart and a "Place order" button
     (`place`). Show edits clearly (strike out the old line, show the new one).
     `rejected` shows the note.
   - **Text:** `confirmed_otc` → cart plus Place order; `needs_prescription` → "This
     needs a prescription. Upload one?"
   - **Failure:** on 502/504/429, a friendly message plus a "Try a sample" button.
4. **Pharmacist console:** a queue list (worst-triage badge, age, total) that polls every
   2 s. The order view shows the prescription image (zoomable) and the lines grouped
   red → amber → green. Each line shows `raw_text`, the parsed fields, the matched SKU,
   reasons, and **approve / edit / remove**. Edit opens an SKU picker (`catalog/search`)
   and a quantity field. The footer has "Approve order" / "Reject with note". Green lines
   get a one-tap "approve all green".
5. **Forecast tab:** a headline card ("Backtest error: our model 21% vs naive 34%"), an
   SKU + area picker, a chart of actual vs forecast with the "now" line, and a reorder
   table with stockout rows highlighted. Use a light chart library (Recharts or uPlot).
6. **Design:** clean and clinical, with Rio's colours if you can find them, otherwise a
   calm teal. Use the `impeccable` or `frontend-design` skill for a design pass.
   Pharmacy-grade legibility matters more than flourish: tabular numbers for prices and a
   clear triage colour system that is colour-blind safe (icons plus colour).

## Wave 2 (H4–H7)

Rebase and point at the real API (`VITE_API_BASE_URL`), locally first and then
`https://rio-api.buildspacelabs.com`. Fix real-data edge cases: long brand names, no
match (`sku: null`), 0 lines parsed, and slow parses. Polish mobile. Check the Pages
build.

## Done means

- `npm run build` and `npm test` are green. Add vitest tests for the mock API state
  machine and money formatting at least. `npm run gen:contracts -- --check` passes.
- `docs/verify/feat-frontend.md` explains how to run with mocks, which clicks walk the
  Loom script, and has screenshots of the split screen, pharmacist edit and forecast tab.
- Push the branch and open the PR after Wave 1 as a draft; mark it ready after Wave 2.

Timebox: Wave 1, 3 h. Wave 2, 3 h.
