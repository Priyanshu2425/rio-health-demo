"""Regenerate contracts/schema.json from app/contracts.py.

    uv run python -m scripts.export_schema # write
    uv run python -m scripts.export_schema --check  # exit 1 if stale

The frontend turns schema.json into src/contracts.gen.ts with `npm run gen:contracts`.
"""

import json
import sys
from pathlib import Path

from pydantic import BaseModel
from pydantic.json_schema import models_json_schema

from app import contracts

OUT = Path(__file__).resolve().parents[2] / "contracts" / "schema.json"


def build() -> str:
    models = [
        obj
        for obj in vars(contracts).values()
        if isinstance(obj, type) and issubclass(obj, BaseModel) and obj.__module__ == contracts.__name__
    ]
    # Requests are what the client sends, so their defaulted fields stay optional.
    requests = {"TextOrderRequest", "SwapRequest", "ItemDecision", "ReviewRequest"}
    pairs = [(m, "validation" if m.__name__ in requests else "serialization") for m in models]
    _, schema = models_json_schema(pairs, title="Rio contracts")
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


if __name__ == "__main__":
    text = build()
    if "--check" in sys.argv:
        if not OUT.exists() or OUT.read_text() != text:
            print("contracts/schema.json is stale; run: uv run python -m scripts.export_schema")
            sys.exit(1)
        print("contracts/schema.json is current")
    else:
        OUT.write_text(text)
        print(f"wrote {OUT}")
