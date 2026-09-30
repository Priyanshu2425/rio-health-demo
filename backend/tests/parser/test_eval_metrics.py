"""Scoring logic of eval/ (pure functions, no network)."""

import json
import sys
from pathlib import Path

import pytest

EVAL_DIR = Path(__file__).resolve().parents[3] / "eval"
sys.path.insert(0, str(EVAL_DIR))

import metrics

TRUTH = {
    "lines": [
        {
            "drug": "Augmentin Duo",
            "strength": "625",
            "doses_per_day": 2,
            "duration_days": 5,
            "composition_key": "amoxycillin 500mg + clavulanic acid 125mg",
        },
        {
            "drug": "Pan",
            "strength": "40",
            "doses_per_day": 1,
            "duration_days": 5,
            "composition_key": "pantoprazole 40mg",
        },
        {
            "drug": "Dolo",
            "strength": "650",
            "doses_per_day": None,
            "duration_days": None,
            "composition_key": "paracetamol 650mg",
        },
    ]
}


def pline(drug, strength, dpd, days, freq="1-0-1", illegible=()):
    return {
        "raw_text": f"Tab {drug}",
        "drug": drug,
        "strength": strength,
        "frequency": freq,
        "doses_per_day": dpd,
        "duration_days": days,
        "illegible_fields": list(illegible),
    }


def match(key, score=0.95, brand="X"):
    return {"sku": {"composition_key": key, "brand_name": brand}, "score": score, "reranked": False}


def test_norm_key_folds_aliases_and_order():
    a = metrics.norm_key("Clavulanic Acid 125 mg + Amoxicillin 500mg")
    assert a == metrics.norm_key("amoxycillin 500mg + clavulanic acid 125mg")
    assert metrics.norm_key("paracetamol 650mg") != metrics.norm_key("paracetamol 500mg")


def test_perfect_parse():
    parsed = {
        "lines": [
            pline("Augmentin", "625", 2, 5),
            pline("Pan", "40 mg", 1, 5),
            pline("Dolo", "650", None, None, freq="SOS"),
        ]
    }
    matches = [match(t["composition_key"]) for t in TRUTH["lines"]]
    s = metrics.score_rx("x", TRUTH, parsed, matches)
    assert s.found == 3 and s.extra == 0
    assert s.fields == {"drug": 3, "strength": 3, "doses_per_day": 3, "duration_days": 3, "quantity": 3}
    assert s.sku_correct == 3
    # Dolo has no frequency count/duration -> completeness < 1 -> amber
    assert s.triage == ["green", "green", "amber"]
    assert s.green_wrong == 0


def test_missing_line_extra_line_and_wrong_sku():
    parsed = {
        "lines": [
            pline("Augmentin", "375", 2, 5),
            pline("Plenty of fluids", None, None, None),
            pline("Dolo", "650", None, None),
        ]
    }
    matches = [
        match("amoxycillin 250mg + clavulanic acid 125mg"),
        {"sku": None, "score": 0},
        match("paracetamol 650mg"),
    ]
    s = metrics.score_rx("x", TRUTH, parsed, matches)
    assert s.found == 2 and s.extra == 1
    assert s.fields["strength"] == 1
    assert s.sku_correct == 1
    assert s.triage[1] == "red"
    assert s.green_wrong == 1  # Augmentin 375 went green but is the wrong SKU
    problems = {f["problem"] for f in s.failures}
    assert {"line not found", "wrong SKU"} <= problems


def test_triage_rules():
    ok = pline("Pan", "40", 1, 5)
    assert metrics.triage(ok, match("k", 0.9)) == "green"
    assert metrics.triage(ok, match("k", 0.7)) == "amber"
    assert metrics.triage(ok, match("k", 0.5)) == "red"
    assert metrics.triage(ok, None) == "red"
    assert metrics.triage(pline("Pan", "40", 1, 5, illegible=["strength"]), match("k", 0.9)) == "amber"
    assert metrics.triage(pline("Pan", "40", 1, 5, illegible=["drug"]), match("k", 0.9)) == "red"


def test_aggregate_without_catalog():
    s = metrics.score_rx("x", TRUTH, {"lines": [pline("Pan", "40", 1, 5)]}, None)
    agg = metrics.aggregate([s], [1000, 3000], [0.001, None])
    assert agg["line_recall"] == pytest.approx(1 / 3)
    assert agg["sku_match_accuracy"] is None and agg["pct_green"] is None
    assert agg["p50_latency_ms"] == 2000
    assert agg["mean_cost_usd"] == pytest.approx(0.0005)


def test_synth_truth_files_are_well_formed():
    files = sorted((EVAL_DIR / "synth").glob("s*.truth.json"))
    assert len(files) == 20
    for f in files:
        truth = json.loads(f.read_text())
        assert 2 <= len(truth["lines"]) <= 5
        for line in truth["lines"]:
            assert {"drug", "strength", "doses_per_day", "duration_days", "composition_key"} <= set(line)
        assert f.with_name(f.name.replace(".truth.json", ".jpg")).exists()
    # a truth file scored against itself is perfect
    truth = json.loads(files[0].read_text())
    s = metrics.score_rx("self", truth, truth, None)
    assert s.found == len(truth["lines"]) and all(v == len(truth["lines"]) for v in s.fields.values())


def test_aggregate_scores_matched_prescriptions_when_one_parse_failed():
    matched = metrics.score_rx(
        "ok", TRUTH, TRUTH, [match(line["composition_key"], 0.9) for line in TRUTH["lines"]]
    )
    failed = metrics.score_rx("failed", TRUTH, {"lines": []}, None)
    agg = metrics.aggregate([matched, failed], [1000, 2000], [0.01, None])
    assert agg["prescriptions"] == 2
    assert agg["sku_scored_prescriptions"] == 1
    assert agg["sku_match_accuracy"] == pytest.approx(1.0)  # over the matched Rx only
    assert agg["line_recall"] == pytest.approx(0.5)  # the failed Rx still counts as missed lines


def test_merge_previous_replaces_only_rerun_prescriptions(tmp_path):
    import run

    saved = {"runs": {"synth": [{"rx_id": "s01", "v": "old"}, {"rx_id": "s19", "v": "old"}]}}
    path = tmp_path / "model.json"
    path.write_text(json.dumps(saved))
    merged = run.merge_previous(path, "synth", [{"rx_id": "s19", "v": "new"}])
    assert merged == [{"rx_id": "s01", "v": "old"}, {"rx_id": "s19", "v": "new"}]
    assert run.merge_previous(tmp_path / "missing.json", "synth", [{"rx_id": "s19"}]) == [{"rx_id": "s19"}]
