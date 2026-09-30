"""Replace the demo samples' cached parses with live parses from VISION_MODEL.

    cd backend && uv run python ../eval/refresh_samples.py [--model <id>]

`make_synth.py --samples` writes truth-derived parses (model "synthetic-truth") so the
fallback works before an API key exists. Run this once the key is set so the cached
parses are real model output, then review the diff before committing.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import get_settings
from app.parser.extract import parse_prescription
from app.parser.samples import SAMPLES_DIR


async def main_async(model: str | None) -> int:
    settings = get_settings()
    model = model or settings.vision_model
    if not settings.openrouter_api_key or not model:
        print("OPENROUTER_API_KEY and --model (or VISION_MODEL) are required", file=sys.stderr)
        return 2
    for entry in json.loads((SAMPLES_DIR / "manifest.json").read_text()):
        image = SAMPLES_DIR / entry["image"]
        parsed = await parse_prescription(image.read_bytes(), entry["mime"], model=model)
        (SAMPLES_DIR / f"{entry['sample_id']}.json").write_text(parsed.model_dump_json(indent=2) + "\n")
        print(f"{entry['sample_id']}: {len(parsed.lines)} lines, {parsed.latency_ms} ms, ${parsed.cost_usd}")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default=None)
    sys.exit(asyncio.run(main_async(ap.parse_args().model)))


if __name__ == "__main__":
    main()
