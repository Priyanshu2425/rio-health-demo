"""Replace the demo samples' cached parses with live parses from VISION_MODEL.

    cd backend && uv run python ../eval/refresh_samples.py [--model <id>] [--only <sample_id> ...]

`make_synth.py --samples` writes truth-derived parses (model "synthetic-truth") so the
fallback works before an API key exists. This re-parses each image in eval/samples/,
writes the parse to eval/samples/<id>.json and upserts it into the `samples` table.
Review the JSON diff before committing it. Costs one vision call per sample; --only
limits the run (and the cost) to the named samples.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(EVAL_DIR.parent / "backend"))

from load_samples import SAMPLES_DIR, connect, manifest, upsert_sample

from app.core.config import get_settings
from app.parser.extract import parse_prescription


async def main_async(model: str | None, only: list[str] | None = None) -> int:
    settings = get_settings()
    model = model or settings.vision_model
    if not settings.openrouter_api_key or not model:
        print("OPENROUTER_API_KEY and --model (or VISION_MODEL) are required", file=sys.stderr)
        return 2
    conn = await connect()
    try:
        entries = list(enumerate(manifest(), start=1))
        unknown = set(only or []) - {e["sample_id"] for _, e in entries}
        if unknown:
            print(f"not in the manifest: {', '.join(sorted(unknown))}", file=sys.stderr)
            return 2
        for position, entry in entries:
            if only and entry["sample_id"] not in only:
                continue
            image = SAMPLES_DIR / entry["image"]
            parsed = await parse_prescription(image.read_bytes(), entry["mime"], model=model)
            (SAMPLES_DIR / f"{entry['sample_id']}.json").write_text(parsed.model_dump_json(indent=2) + "\n")
            await upsert_sample(conn, entry, position, parsed)
            print(
                f"{entry['sample_id']}: {len(parsed.lines)} lines, {parsed.latency_ms} ms, ${parsed.cost_usd}"
            )
    finally:
        await conn.close()
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default=None)
    ap.add_argument("--only", nargs="+", default=None, metavar="SAMPLE_ID", help="refresh only these samples")
    args = ap.parse_args()
    sys.exit(asyncio.run(main_async(args.model, args.only)))


if __name__ == "__main__":
    main()
