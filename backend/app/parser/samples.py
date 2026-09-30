"""Demo prescriptions with cached parses: the 'try a sample' fallback.

Each sample is `samples/<id>.jpg` plus `samples/<id>.json` (a ParsedRx), listed in
`samples/manifest.json` as `[{"sample_id", "label", "mime"}]`.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from app.contracts import ParsedRx, Sample

SAMPLES_DIR = Path(__file__).parent / "samples"


@lru_cache
def _manifest() -> list[dict[str, str]]:
    return json.loads((SAMPLES_DIR / "manifest.json").read_text())


def list_samples() -> list[Sample]:
    return [
        Sample(
            sample_id=s["sample_id"], label=s["label"], thumbnail_url=f"/api/samples/{s['sample_id']}/image"
        )
        for s in _manifest()
    ]


def load_sample(sample_id: str) -> tuple[bytes, str, ParsedRx]:
    entry = next((s for s in _manifest() if s["sample_id"] == sample_id), None)
    if entry is None:
        raise KeyError(sample_id)
    image = (SAMPLES_DIR / entry["image"]).read_bytes()
    parsed = ParsedRx.model_validate_json((SAMPLES_DIR / f"{sample_id}.json").read_text())
    return image, entry["mime"], parsed
