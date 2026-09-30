# Verify: feat/parser-eval

Prescription parser, SKU matcher, typed-text splitter, demo samples and the eval harness.

**Status:** everything that runs without an OpenRouter key is built and tested. The key
was not in `.env` when this branch was pushed, so there are no vision-model numbers yet.
The matcher alone has been measured against the live catalog (9,303 SKUs loaded by
feat/data-forecast), using the "oracle" mode below. Section 3 lists the exact commands
to run once `OPENROUTER_API_KEY` is set.

## 1. Unit tests (no network, no database)

```sh
cd backend && uv run ruff check . && uv run ruff format --check . && uv run pytest -q
```

Expected: all pass, 2 skipped. The skipped ones are the `llm` tests in
`tests/parser/test_llm_live.py`; they run only with `RUN_LLM=1`, a key and
`VISION_MODEL`/`RERANK_MODEL` set:

```sh
cd backend && RUN_LLM=1 uv run pytest -q tests/parser -m llm
```

What the unit tests cover: frequency → `doses_per_day` (`1-0-1`, `½-0-½`, BD, `t.d.s`,
q8h, SOS…), duration → days (`x 5 days`, `5/7`, `2/52`, `1/12`), form prefixes, dates,
LLM output → `ParsedRx` mapping, image downscale to ≤ 1600 px, quantity in units
(contracts-v2), the matcher with a fake catalog and fake LLM (confident path skips the
LLM, ambiguous path re-ranks, re-rank failure or no model falls back deterministically),
the text splitter, the samples, and the eval scoring functions.

## 2. Matcher-only eval (no key needed)

`--model oracle` feeds the truth lines to the matcher as if the vision model had read
them perfectly, so it measures catalog search + matching alone, at no cost.

```sh
cd backend && uv run python ../eval/sync_truth.py        # every truth brand/key exists in skus
cd backend && uv run python ../eval/run.py --model oracle --set synth
```

Result (read-only pg_trgm adapter over `skus`, no re-rank model, so ambiguous lines used
the deterministic fallback):

| Set | Rx | Truth lines | SKU match | Green | Amber | Red | Green but wrong | p50 | p95 |
|---|---|---|---|---|---|---|---|---|---|
| synth | 20 | 77 | **100%** | 60% | 40% | 0 | 0 | 1.4 s | 1.9 s |

Amber lines are expected: lines with no written strength (Pan-D, Combiflam, Montair LC)
or SOS with no duration have completeness < 1, and ambiguous matches without a re-rank
keep their trigram score (< 0.85). Latency here is Neon round trips from a laptop.

## 3. Once `OPENROUTER_API_KEY` is set

Model ids and prices checked on https://openrouter.ai/api/v1/models on 2026-09-30
(USD per million tokens, input/output): `google/gemini-3.8-flash` 0.75/3.75,
`anthropic/claude-sonnet-5.5` 2/10, `openai/gpt-6.1-sol` 2/10; cheap re-rank
candidates `openai/gpt-6-luna` 0.10/0.50 and `google/gemini-3.5-flash-lite` 0.30/2.50.
Re-check before running. Estimated cost: about $0.01 per prescription for the two
larger models and less for Gemini Flash, so the whole comparison (3 models × 20 synthetic
+ 10 handwritten) is about $1, well under the $3 budget.

```sh
cd backend
# smoke test: 2 prescriptions, check the numbers look sane
uv run python ../eval/run.py --model google/gemini-3.8-flash --rerank-model openai/gpt-6-luna --set synth --limit 2
# the comparison (each appends to eval/results/summary.md)
uv run python ../eval/run.py --model google/gemini-3.8-flash    --rerank-model openai/gpt-6-luna --set all
uv run python ../eval/run.py --model anthropic/claude-sonnet-5.5 --rerank-model openai/gpt-6-luna --set all
uv run python ../eval/run.py --model openai/gpt-6.1-sol         --rerank-model openai/gpt-6-luna --set all
cat ../eval/results/summary.md
```

Then set `VISION_MODEL` (best SKU match on synth, then p95 latency and cost) and
`RERANK_MODEL` in `.env`, and replace the demo samples' truth-derived parses with real
ones:

```sh
cd backend && uv run python ../eval/refresh_samples.py
```

3 example parses: run the command below and paste its output here.

```sh
cd backend && uv run python -c "
import asyncio, json
from pathlib import Path
from app.parser.extract import parse_prescription
async def main():
    for sid in ('typed_clinic_3', 'hospital_opd_4', 'handwritten_style_3'):
        rx = await parse_prescription(Path('../eval/samples', sid + '.jpg').read_bytes(), 'image/jpeg')
        print(sid, rx.model, rx.latency_ms, 'ms', rx.cost_usd)
        for l in rx.lines: print('  ', json.dumps(l.model_dump(mode='json', exclude={'bbox'})))
asyncio.run(main())"
```

## 4. Handwritten set

Empty until the owner adds `eval/handwritten/hw_NN.jpg`; `run.py` skips it meanwhile.
See `eval/handwritten/README.md`. After adding the photos:

```sh
cd backend && uv run python ../eval/prefill_handwritten.py --model <VISION_MODEL>
```

**The truth files this writes are the model's own parse, marked `"_prefilled": true`.
They are not ground truth until the owner corrects each one against the paper and
deletes the `_prefilled` lines.** `run.py` skips files that are still marked.

## 5. Demo samples

Served from the `samples` table (migration 002). `list_samples(conn)` and
`load_sample(conn, id)` are plain queries; no request path opens a file (a grep of
`backend/app/parser` for `read_bytes`, `read_text` or `open(` finds only
`Image.open(io.BytesIO(...))`). The images and cached parses in `eval/samples/` are ETL
input, loaded with an idempotent upsert:

```sh
cd backend && uv run python ../eval/load_samples.py            # prints "samples rows: 3"
cd backend && uv run pytest -q tests/parser/test_samples.py    # db-marked, read-only
```

The samples are `typed_clinic_3` (Augmentin 625 Duo, Pan 40, Dolo 650), `hospital_opd_4`
(Azithral 500, Montair LC, Pan-D, Calpol 500) and `handwritten_style_3` (Telma 40,
Glycomet 500, Atorva 10, in a handwriting font). All three are synthetic for now;
`handwritten_style_3` should be replaced by one of the owner's handwritten photos (copy
it into `eval/samples/`, edit `manifest.json`, run `load_samples.py`). Their cached
parses are built from the generator's truth (`"model": "synthetic-truth"`) until
`refresh_samples.py` runs; it writes the live parse to both the JSON file and the table.

## 6. Regenerating the synthetic set

```sh
cd backend && uv run python ../eval/make_synth.py            # eval/synth/s01..s20 (+ .truth.json)
cd backend && uv run python ../eval/make_synth.py --samples  # eval/samples/, then load_samples.py
```

Deterministic for a given `--seed`, using macOS system fonts (Arial, Georgia, Times,
Verdana, Courier, Trebuchet, Tahoma; handwriting-style Bradley Hand, Noteworthy, Marker
Felt, Chalkboard, Comic Sans). Four layouts: clinic letterhead, hospital OPD table,
handwritten on a pad (with struck-through lines that are not in the truth) and minimal
typed with C/O, O/E, advice and investigations as distractors. Degradation: page on a
table, perspective warp, rotation ±4°, lighting gradient and vignette, paper tint,
noise, blur, JPEG quality 40–70.
