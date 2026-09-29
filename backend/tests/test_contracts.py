import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from app import contracts as c

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "contracts" / "fixtures"

SHAPES = {
    "parsed_rx.json": c.ParsedRx,
    "order_pending_review.json": c.Order,
    "order_verified.json": c.Order,
    "order_text_otc.json": c.Order,
    "queue.json": list[c.QueueItem],
    "catalog_search.json": list[c.MatchCandidate],
    "samples.json": list[c.Sample],
    "forecast_summary.json": c.ForecastSummary,
    "sku_forecast.json": c.SkuForecast,
}


@pytest.mark.parametrize("name,shape", SHAPES.items())
def test_fixture_matches_contract(name, shape):
    TypeAdapter(shape).validate_python(json.loads((FIXTURES / name).read_text()))


def test_every_fixture_is_checked():
    assert {p.name for p in FIXTURES.glob("*.json")} == set(SHAPES)


def test_schema_json_is_current():
    result = subprocess.run(
        [sys.executable, "-m", "scripts.export_schema", "--check"],
        cwd=ROOT / "backend",
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
