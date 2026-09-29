# 02: Parser + Eval (`feat/parser-eval`)

Read first: `docs/DECISIONS.md`, `contracts/README.md`, `backend/app/contracts.py`,
`backend/app/core/llm.py`, `contracts/API.md` (the order rules section).

## You own

`backend/app/parser/`, `eval/`, `backend/tests/parser/`, `docs/verify/feat-parser-eval.md`.
Touch nothing else. If you need a contract or dependency change, stop and report it.

## What to build

1. **`parse_prescription(image, mime) -> ParsedRx`:**
   - Downscale the image to ≤ 1600 px on the long side (Pillow) before sending.
   - One call through `app.core.llm.complete_json` with `VISION_MODEL`. Define your own
     LLM-output model inside `app/parser/` (it can be simpler than `ParsedRx`), then map
     it to `ParsedRx`.
   - The prompt covers Indian prescription conventions: `Tab./Cap./Syp./Inj.`, frequency
     notations (`1-0-1`, `1-1-1`, `0-0-1`, OD, BD, TDS, QID, HS, SOS, `x 5 days`, `5/7`),
     "before/after food", strikethroughs, and the letterhead vs the Rx lines. Transcribe
     `raw_text` literally, and mark a field in `illegible_fields` instead of guessing.
   - Normalize `doses_per_day` in code from `frequency`, not in the prompt (a table: BD=2,
     TDS=3, `1-0-1`=2, SOS=None…).
2. **`match_line(conn, line) -> MatchResult`:** `app.catalog.search` on drug + strength
   (top 5). If the top score is ≥ 0.85 and beats the second by ≥ 0.1, take it without an
   LLM call. Otherwise call `RERANK_MODEL` with the parsed line and the 5 candidates,
   asking it to pick an index or "none" with a reason. Prefer a candidate whose strength
   and form match the line.
3. **`match_text(conn, text)`:** split typed requests ("crocin and 2 ORS, dolo") with a
   small rule-based splitter; an LLM is fine as a fallback. Match each part.
4. **Samples:** `app/parser/samples/` with 3 demo images (2 synthetic, 1 of the
   owner's handwritten ones) plus a cached `ParsedRx` JSON for each. Implement
   `list_samples` and `load_sample`. `thumbnail_url` = `/api/samples/{id}/image`.
5. **Until the catalog lands:** `app.catalog.search` raises `NotImplementedError` on your
   branch. Unit-test `match_line` with a fake `search` (monkeypatch). The end-to-end
   SKU-accuracy eval runs after you rebase on the merged `feat/data-forecast`.

## Eval (`eval/`)

1. **Synthetic set** (`eval/synth/`, 20 prescriptions): `eval/make_synth.py` renders clinic
   letterheads with Pillow (3–4 layouts, several fonts, including 2 handwriting-style
   ones), 2–5 lines each, drawn from real brand names in the catalog seed. Then degrade
   each one: rotation ±4°, perspective warp, blur, JPEG quality 40–70, an uneven-lighting
   gradient. Write `sNN.jpg` plus `sNN.truth.json` at generation time.
2. **Handwritten set** (`eval/handwritten/`): the owner provides `hw_NN.jpg`. For each,
   create `hw_NN.truth.json` for the owner to fill in. Pre-fill it with your parse so the
   owner only corrects it, and say so clearly in VERIFY.
3. **Truth format:** `{"lines": [{"drug": "...", "strength": "...", "doses_per_day": 2,
   "duration_days": 5, "composition_key": "..."}]}`.
4. **`eval/run.py --model <id> [--set synth|handwritten|all]`**, per set:
   - **Line recall:** truth lines found; align by best fuzzy match on drug
   - **Field accuracy:** drug, strength, doses_per_day, duration_days
   - **SKU match accuracy:** the matched SKU's `composition_key` equals the truth
   - **% green:** triage rules from `contracts/API.md`
   - p50/p95 latency and the mean cost per prescription

   Write `eval/results/<model>.json` and append to `eval/results/summary.md`.
5. **Model comparison:** run 3 vision candidates on OpenRouter: one Gemini Flash-class,
   one Claude Sonnet-class and one GPT-class. Check current ids and prices on
   openrouter.ai/models; don't rely on memory. Recommend `VISION_MODEL` and a cheap
   `RERANK_MODEL`. The whole comparison should cost under about $3; stop and report if
   it won't.

## Done means

- `uv run pytest -q` is green. Unit tests need no network. LLM tests are marked `llm`
  and skipped by default.
- The H4 gate: SKU match ≥ 80% on synthetic with the recommended model. If you miss it,
  report the numbers and the top failure modes rather than tuning forever.
- `docs/verify/feat-parser-eval.md` gives commands to reproduce `summary.md`, plus 3
  example parses.
- Push the branch and open a PR. The PR body includes the comparison table.

Timebox: 3.5 h including eval runs.
