"""Pre-fill truth files for the owner's handwritten prescriptions.

    cd backend && uv run python ../eval/prefill_handwritten.py [--model <id>]

For each eval/handwritten/hw_NN.jpg without hw_NN.truth.json, parse it with the vision
model and write a truth file marked `"_prefilled": true`. The owner corrects each file
against the paper and deletes the `_prefilled` line; `run.py` skips files still marked.
`composition_key` is left empty unless the catalog is loaded and matching finds one;
check it too.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(EVAL_DIR.parent / "backend"))

from run import mime_for, resolve_search

from app import catalog
from app.core.config import get_settings
from app.parser.extract import parse_prescription
from app.parser.match import match_line_detailed

FOLDER = EVAL_DIR / "handwritten"


async def main_async(model: str | None) -> int:
    settings = get_settings()
    model = model or settings.vision_model
    if not settings.openrouter_api_key or not model:
        print("OPENROUTER_API_KEY and --model (or VISION_MODEL) are required", file=sys.stderr)
        return 2
    images = sorted(p for p in FOLDER.glob("hw_*") if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"})
    todo = [p for p in images if not p.with_suffix(".truth.json").exists()]
    if not todo:
        print(f"nothing to prefill ({len(images)} images, all have truth files)")
        return 0
    search_fn, conn, label = await resolve_search("auto")
    print(f"catalog: {label}")
    try:
        for image in todo:
            parsed = await parse_prescription(image.read_bytes(), mime_for(image), model=model)
            lines = []
            for line in parsed.lines:
                key = ""
                if search_fn is not None:
                    catalog.search = search_fn
                    result = (await match_line_detailed(conn, line)).result
                    key = result.sku.composition_key if result.sku else ""
                lines.append(
                    {
                        "drug": line.drug,
                        "strength": line.strength,
                        "doses_per_day": line.doses_per_day,
                        "duration_days": line.duration_days,
                        "quantity": line.quantity,
                        "composition_key": key,
                        "raw_text": line.raw_text,
                    }
                )
            truth = {"_prefilled": True, "_prefilled_by": parsed.model, "lines": lines}
            image.with_suffix(".truth.json").write_text(json.dumps(truth, indent=2) + "\n")
            print(f"{image.name}: {len(lines)} lines prefilled")
    finally:
        if conn is not None:
            await conn.close()
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default=None)
    sys.exit(asyncio.run(main_async(ap.parse_args().model)))


if __name__ == "__main__":
    main()
