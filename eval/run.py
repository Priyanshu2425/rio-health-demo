"""Run the parser eval.

    cd backend && uv run python ../eval/run.py --model google/gemini-3.8-flash --set synth
    cd backend && uv run python ../eval/run.py --model <id> --rerank-model <id> --set all

Per set: line recall, field accuracy (drug, strength, doses_per_day, duration_days),
SKU match accuracy (matched SKU's composition_key equals the truth), % green (triage
rules from contracts/API.md), p50/p95 latency and mean cost per prescription.
Writes eval/results/<model>.json and appends rows to eval/results/summary.md.

SKU matching needs a populated `skus` table. `--catalog auto` uses `app.catalog.search`
if it is implemented, else the read-only eval adapter (`catalog_adapter.py`), else skips
SKU metrics. Handwritten truth files still marked `"_prefilled": true` are skipped until
the owner has checked them.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

EVAL_DIR = Path(__file__).resolve().parent
ROOT = EVAL_DIR.parent
sys.path.insert(0, str(ROOT / "backend"))

import catalog_adapter
import metrics

from app import catalog
from app.contracts import ParsedLine, ParsedRx
from app.core.config import get_settings
from app.core.llm import LLMError
from app.parser.extract import parse_prescription
from app.parser.normalize import form_from_text
from app.parser.match import match_line_detailed

SETS = {"synth": EVAL_DIR / "synth", "handwritten": EVAL_DIR / "handwritten"}
RESULTS = EVAL_DIR / "results"


def load_set(name: str) -> list[tuple[str, Path, dict]]:
    """[(rx_id, image_path, truth)] for every image that has a checked truth file."""
    folder = SETS[name]
    items = []
    for image in sorted(
        p for p in folder.glob("*") if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
    ):
        truth_path = image.with_suffix(".truth.json")
        if not truth_path.exists():
            print(f"  skip {image.name}: no truth file", file=sys.stderr)
            continue
        truth = json.loads(truth_path.read_text())
        if truth.get("_prefilled"):
            print(f"  skip {image.name}: truth still prefilled (not checked by the owner)", file=sys.stderr)
            continue
        items.append((image.stem, image, truth))
    return items


ORACLE = "oracle"


def oracle_parse(truth: dict) -> ParsedRx:
    """A perfect parse built from the truth file: measures the matcher alone, at no cost."""
    lines = [
        ParsedLine(
            line_no=i,
            raw_text=t.get("raw_text") or t["drug"],
            drug=t["drug"],
            strength=t.get("strength"),
            form=form_from_text(t.get("raw_text", "").split(" ")[0]),
            frequency="as truth",
            doses_per_day=t.get("doses_per_day"),
            duration_days=t.get("duration_days"),
            quantity=t.get("quantity"),
        )
        for i, t in enumerate(truth["lines"], start=1)
    ]
    return ParsedRx(lines=lines, model=ORACLE, latency_ms=0, cost_usd=0.0)


def mime_for(path: Path) -> str:
    return {".png": "image/png", ".webp": "image/webp"}.get(path.suffix.lower(), "image/jpeg")


async def resolve_search(mode: str):
    """Return (search_fn, conn, label) or (None, None, reason)."""
    if mode == "off":
        return None, None, "disabled (--catalog off)"
    settings = get_settings()
    if not settings.database_url:
        return None, None, "RIO_HEALTH_DATABASE_URL not set"
    conn = await catalog_adapter.connect_read_only(settings.database_url, settings.db_schema)
    count = await catalog_adapter.sku_count(conn)
    if count == 0:
        await conn.close()
        return None, None, "skus table is empty"
    if mode in ("auto", "app"):
        try:
            await catalog.search(conn, "dolo 650", limit=1)
            return catalog.search, conn, f"app.catalog.search ({count} SKUs)"
        except NotImplementedError:
            if mode == "app":
                await conn.close()
                return None, None, "app.catalog.search not implemented on this branch"
    return catalog_adapter.search, conn, f"eval adapter, read-only pg_trgm ({count} SKUs)"


async def eval_one(rx_id, image_path, truth, args, search_fn, conn, sem) -> dict[str, Any]:
    async with sem:
        started = time.perf_counter()
        try:
            if args.model == ORACLE:
                parsed = oracle_parse(truth)
            else:
                parsed = await parse_prescription(
                    image_path.read_bytes(), mime_for(image_path), model=args.model
                )
        except LLMError as exc:
            print(f"  {rx_id}: parse failed: {exc}", file=sys.stderr)
            return {
                "rx_id": rx_id,
                "error": str(exc),
                "parsed": {"lines": []},
                "matches": None,
                "latency_ms": (time.perf_counter() - started) * 1000,
                "parse_latency_ms": None,
                "cost_usd": None,
            }
        cost = parsed.cost_usd
        matches = None
        if search_fn is not None:
            catalog.search = search_fn  # match_line_detailed calls app.catalog.search
            matches = []
            for line in parsed.lines:
                outcome = await match_line_detailed(conn, line, rerank_model=args.rerank_model)
                matches.append(outcome.result.model_dump(mode="json"))
                if outcome.cost_usd is not None:
                    cost = (cost or 0.0) + outcome.cost_usd
        latency = (time.perf_counter() - started) * 1000
        n = len(parsed.lines)
        print(f"  {rx_id}: {n} lines, {parsed.latency_ms} ms parse, {latency:.0f} ms total")
        return {
            "rx_id": rx_id,
            "parsed": parsed.model_dump(mode="json"),
            "matches": matches,
            "latency_ms": latency,
            "parse_latency_ms": parsed.latency_ms,
            "cost_usd": cost,
        }


def results_path(model: str) -> Path:
    return RESULTS / (model.replace("/", "__").replace(":", "_") + ".json")


def fmt_pct(x):
    return "n/a" if x is None else f"{100 * x:.0f}%"


def coverage(agg: dict) -> str:
    """' (18/20 Rx)' when some prescriptions could not be matched, else ''."""
    scored = agg.get("sku_scored_prescriptions")
    if scored is None or agg["sku_match_accuracy"] is None or scored == agg["prescriptions"]:
        return ""
    return f" ({scored}/{agg['prescriptions']} Rx)"


def merge_previous(path: Path, name: str, runs: list[dict]) -> list[dict]:
    """Replace, in the saved runs of set `name`, the prescriptions that were just re-run.

    Used with --only: re-running two failed prescriptions keeps the other results and
    the whole set is re-scored, so no paid call is repeated.
    """
    if not path.exists():
        return runs
    saved = json.loads(path.read_text()).get("runs", {}).get(name, [])
    fresh = {r["rx_id"]: r for r in runs}
    merged = [fresh.pop(r["rx_id"], r) for r in saved]
    return merged + list(fresh.values())


def summary_rows(model: str, rerank: str | None, catalog_label: str, sets: dict[str, dict]) -> list[str]:
    rows = []
    date = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
    for name, agg in sets.items():
        fa = agg["field_accuracy"]
        cost = agg["mean_cost_usd"]
        rows.append(
            f"| {date} | {name} | `{model}` | `{rerank or '-'}` | {agg['prescriptions']} | "
            f"{fmt_pct(agg['line_recall'])} | {fmt_pct(fa['drug'])} | {fmt_pct(fa['strength'])} | "
            f"{fmt_pct(fa['doses_per_day'])} | {fmt_pct(fa['duration_days'])} | "
            f"**{fmt_pct(agg['sku_match_accuracy'])}**{coverage(agg)} | {fmt_pct(agg['pct_green'])} | "
            f"{agg.get('green_but_wrong', 'n/a')} | "
            f"{(agg['p50_latency_ms'] or 0) / 1000:.1f} s | {(agg['p95_latency_ms'] or 0) / 1000:.1f} s | "
            f"{'n/a' if cost is None else f'${cost:.4f}'} |"
        )
    return rows


SUMMARY_HEADER = """# Eval summary

Appended by `eval/run.py`. Recall, field and SKU accuracy are over truth lines; % green is
over parsed lines; latency is parse + match per prescription; cost is per prescription.

| When (UTC) | Set | Vision model | Re-rank model | Rx | Line recall | Drug | Strength | Doses/day | Days | SKU match | Green | Green but wrong | p50 | p95 | $/Rx |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
"""


async def main_async(args) -> int:
    settings = get_settings()
    if not settings.openrouter_api_key and args.model != ORACLE:
        print("OPENROUTER_API_KEY is not set in .env; only --model oracle can run.", file=sys.stderr)
        return 2
    args.rerank_model = args.rerank_model or settings.rerank_model or None

    names = ["synth", "handwritten"] if args.set == "all" else [args.set]
    search_fn, conn, catalog_label = await resolve_search(args.catalog)
    print(f"catalog: {catalog_label}")
    if search_fn is None:
        print("SKU match accuracy and % green will be n/a.")

    sem = asyncio.Semaphore(args.concurrency)
    per_set: dict[str, dict] = {}
    raw: dict[str, list] = {}
    try:
        for name in names:
            all_items = load_set(name)
            items = all_items[: args.limit or None]
            if args.only:
                items = [it for it in all_items if it[0] in args.only]
                unknown = args.only - {it[0] for it in items}
                if unknown:
                    print(f"{name}: no such prescriptions: {', '.join(sorted(unknown))}", file=sys.stderr)
            if not items:
                print(f"{name}: no images with checked truth; skipped")
                continue
            print(f"{name}: {len(items)} prescriptions with {args.model}")
            runs = await asyncio.gather(
                *(eval_one(rx_id, img, truth, args, search_fn, conn, sem) for rx_id, img, truth in items)
            )
            if args.only:
                runs = merge_previous(results_path(args.model), name, list(runs))
            truths = {rx_id: truth for rx_id, _, truth in all_items}
            scores = []
            for run in runs:
                s = metrics.score_rx(run["rx_id"], truths[run["rx_id"]], run["parsed"], run["matches"])
                run["score"] = s.__dict__
                scores.append(s)
            agg = metrics.aggregate(scores, [r["latency_ms"] for r in runs], [r["cost_usd"] for r in runs])
            agg["parse_errors"] = sum(1 for r in runs if r.get("error"))
            per_set[name] = agg
            raw[name] = runs
            print(json.dumps(agg, indent=2))
    finally:
        if conn is not None:
            await conn.close()

    if not per_set:
        return 1
    RESULTS.mkdir(exist_ok=True)
    out = {
        "model": args.model,
        "rerank_model": args.rerank_model,
        "catalog": catalog_label,
        "generated_at": datetime.now(UTC).isoformat(),
        "sets": per_set,
        "runs": raw,
    }
    results_path(args.model).write_text(json.dumps(out, indent=2, default=str) + "\n")
    summary = RESULTS / "summary.md"
    if not summary.exists():
        summary.write_text(SUMMARY_HEADER)
    with summary.open("a") as f:
        f.write("\n".join(summary_rows(args.model, args.rerank_model, catalog_label, per_set)) + "\n")
    print(f"wrote {results_path(args.model)} and appended to {summary}")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "--model", required=True, help="OpenRouter vision model id, or 'oracle' to score the matcher alone"
    )
    ap.add_argument("--rerank-model", default=None, help="defaults to RERANK_MODEL")
    ap.add_argument("--set", choices=["synth", "handwritten", "all"], default="all")
    ap.add_argument("--catalog", choices=["auto", "app", "adapter", "off"], default="auto")
    ap.add_argument("--limit", type=int, default=0, help="only the first N prescriptions per set")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument(
        "--only",
        type=lambda v: {x.strip() for x in v.split(",") if x.strip()},
        default=None,
        help="re-run only these rx ids (e.g. s19,s20) and merge them into the saved results for --model",
    )
    sys.exit(asyncio.run(main_async(ap.parse_args())))


if __name__ == "__main__":
    main()
