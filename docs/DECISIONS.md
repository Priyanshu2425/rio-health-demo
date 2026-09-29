# Decisions

Settled in the planning session on 2026-09-29. Change one only by editing this file on `main`.

1. **Audience.** Rio's founders or hiring team. They should come away with: "understands
   regulated pharmacy ordering over WhatsApp, and ships end to end." Parse → cart →
   pharmacist queue is the product. Forecast is a bonus and the first thing cut.
2. **Stack.** FastAPI (Python 3.12+), Neon Postgres, OpenRouter for every LLM call, and
   Vite + React + TypeScript.
3. **Hosting.** The frontend is on Cloudflare Pages at `rio.buildspacelabs.com`. The API
   runs on one EC2 instance behind a Cloudflare Tunnel at `rio-api.buildspacelabs.com`.
   Only SSH is open. Hostnames are one level deep because Cloudflare's free certificate
   covers only `*.buildspacelabs.com`.
4. **Database.** Schema `app_rio_health` on the shared Neon project, provisioned by
   `~/Desktop/buildspace/neon` with the direct endpoint. `pg_trgm` is installed
   database-wide by the admin.
5. **Compliance model.** Every prescription order gets a pharmacist check, because
   Schedule H/H1 drugs legally need one. Confidence doesn't decide *whether* a pharmacist
   reviews an order; it decides how: green, amber or red per line. OTC-only typed orders
   skip the queue. Typed requests for Rx-only items get "please upload a prescription."
6. **Confidence is computed, not self-reported.** It combines the catalog match score,
   field completeness and per-field legibility. The model's own confidence number is
   never used.
7. **Catalog.** Kaggle "A-Z Medicine Dataset of India", trimmed to 5–10k SKUs.
   Composition is normalized to `(salt, strength)` pairs and a `composition_key`. Equal
   keys mean the SKUs can be substituted, which is how generic alternatives are found.
   Rx-only comes from a hand-curated Schedule H/H1/X salt list, and the README says it
   is approximate.
8. **Pipeline.** Vision extract (JSON schema, no catalog knowledge) → `pg_trgm`
   candidates → LLM re-rank only when the match is ambiguous. Quantity is computed in
   code, never by the LLM. Model ids are environment variables chosen by the eval.
9. **Eval.** 20 synthetic prescriptions, degraded to look like phone photos, plus 10 real
   handwritten ones written and photographed by the owner, reported separately. The
   headline metric is SKU match accuracy. The README includes a model comparison table
   (accuracy, p95 latency, cost). Gate: SKU match ≥ 80% on synthetic.
10. **UX.** A split-screen demo at `/` (customer chat on the left, pharmacist console on
    the right), plus `/chat`, `/pharmacist` and `/forecast`. The chat polls the order
    every 2 s.
11. **Forecast, trimmed.** About 50 SKUs × 3 areas of synthetic hourly orders with an
    hour-of-week curve and one injected spike. The model is a seasonal baseline × a
    7-day moving level, with one backtest number against "same hour last week." One
    chart and one reorder table. No safety-stock statistics.
12. **Abuse guard.** 10 parses per IP per hour, 5 MB uploads, a spend cap on the
    OpenRouter key, and "try a sample" as the fallback whenever the parser fails.
13. **Out of scope** (listed as "next" in the README): the real WhatsApp API, auth,
    payments and delivery.
14. **Process.** Four agents, one branch each, with disjoint directory ownership.
    Contracts are frozen on `main`. Each branch ships tests and a `VERIFY.md`, and the
    owner merges every PR.
