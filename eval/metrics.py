"""Pure scoring functions for the eval (no network, no database)."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

from rapidfuzz import fuzz

ALIGN_MIN = 70  # min fuzzy score to call a parsed line the same line as a truth line
DRUG_OK = 85  # min fuzzy score for the drug field to count as correct

SALT_ALIASES = {
    "amoxicillin": "amoxycillin",
    "acetaminophen": "paracetamol",
    "clavulanate": "clavulanic acid",
    "potassium clavulanate": "clavulanic acid",
    "levothyroxine": "thyroxine",
    "thyroxine sodium": "thyroxine",
    "acetylsalicylic acid": "aspirin",
    "metformin hydrochloride": "metformin",
    "ondansetron hydrochloride": "ondansetron",
    "dicycloverine": "dicyclomine",
}


def norm_name(text: str | None) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower()).strip()


def norm_key(key: str | None) -> str:
    """Canonical composition key for comparison: aliases folded, spaces dropped, salts sorted."""
    if not key:
        return ""
    parts = []
    for part in key.lower().split("+"):
        part = re.sub(r"\s+", " ", part).strip()
        m = re.match(r"^(.*?)\s*(\d[\d./]*\s*[a-z%/]*)?$", part)
        name, strength = (m.group(1), m.group(2) or "") if m else (part, "")
        name = SALT_ALIASES.get(name.strip(), name.strip())
        parts.append(f"{name}{strength.replace(' ', '')}".replace(" ", ""))
    return "+".join(sorted(parts))


def _numbers(text: str | None) -> list[str]:
    nums = re.findall(r"\d+(?:\.\d+)?", text or "")
    return sorted(n.rstrip("0").rstrip(".") if "." in n else n for n in nums)


def drug_score(truth: str | None, pred: str | None) -> float:
    a, b = norm_name(truth), norm_name(pred)
    if not a or not b:
        return 0.0
    return max(fuzz.token_set_ratio(a, b), fuzz.ratio(a, b))


def align(truth_lines: list[dict], pred_lines: list[dict]) -> list[tuple[int, int | None]]:
    """Greedy one-to-one alignment on drug similarity. Returns (truth_idx, pred_idx|None)."""
    pairs = []
    for ti, t in enumerate(truth_lines):
        for pi, p in enumerate(pred_lines):
            score = drug_score(t.get("drug"), p.get("drug"))
            if score < ALIGN_MIN:
                # fall back to the raw line, e.g. when the drug field is null but raw_text has it
                score = max(
                    score, fuzz.partial_ratio(norm_name(t.get("drug")), norm_name(p.get("raw_text"))) - 10
                )
            if score >= ALIGN_MIN:
                pairs.append((score, ti, pi))
    pairs.sort(key=lambda x: -x[0])
    used_t: set[int] = set()
    used_p: set[int] = set()
    out: dict[int, int | None] = {i: None for i in range(len(truth_lines))}
    for _, ti, pi in pairs:
        if ti in used_t or pi in used_p:
            continue
        out[ti] = pi
        used_t.add(ti)
        used_p.add(pi)
    return sorted(out.items())


def _num_eq(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return math.isclose(float(a), float(b), abs_tol=0.01)


def field_hits(truth: dict, pred: dict) -> dict[str, bool]:
    return {
        "drug": drug_score(truth.get("drug"), pred.get("drug")) >= DRUG_OK,
        "strength": _numbers(truth.get("strength")) == _numbers(pred.get("strength")),
        "doses_per_day": _num_eq(truth.get("doses_per_day"), pred.get("doses_per_day")),
        "duration_days": _num_eq(truth.get("duration_days"), pred.get("duration_days")),
        "quantity": _num_eq(truth.get("quantity"), pred.get("quantity")),
    }


def completeness(line: dict) -> float:
    present = [
        bool(line.get("drug")),
        bool(line.get("strength")),
        bool(line.get("frequency")),
        line.get("duration_days") is not None,
    ]
    return sum(present) / len(present)


def triage(line: dict, match: dict | None) -> str:
    """Per-line triage from contracts/API.md, from a ParsedLine and MatchResult as dicts."""
    illegible = line.get("illegible_fields") or []
    sku = (match or {}).get("sku")
    score = (match or {}).get("score") or 0.0
    if sku is None or "drug" in illegible or score < 0.6:
        return "red"
    if score < 0.85 or completeness(line) < 1 or illegible:
        return "amber"
    return "green"


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    k = (len(s) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


@dataclass
class RxScore:
    """Scores for one prescription."""

    rx_id: str
    truth_lines: int
    found: int
    extra: int
    fields: dict[str, int] = field(default_factory=dict)  # field -> correct count over truth lines
    sku_evaluated: bool = False
    sku_correct: int = 0
    triage: list[str] = field(default_factory=list)
    green_wrong: int = 0
    failures: list[dict[str, Any]] = field(default_factory=list)


def score_rx(rx_id: str, truth: dict, parsed: dict, matches: list[dict | None] | None) -> RxScore:
    """Score one prescription. `matches[i]` is the MatchResult (as a dict) for parsed line i,
    or `matches` is None when SKU matching did not run."""
    t_lines = truth["lines"]
    p_lines = parsed.get("lines", [])
    alignment = align(t_lines, p_lines)
    s = RxScore(rx_id=rx_id, truth_lines=len(t_lines), found=0, extra=0)
    s.fields = {"drug": 0, "strength": 0, "doses_per_day": 0, "duration_days": 0, "quantity": 0}
    matched_preds = {pi for _, pi in alignment if pi is not None}
    s.extra = len(p_lines) - len(matched_preds)
    s.sku_evaluated = matches is not None
    correct_by_pred: dict[int, bool] = {}
    for ti, pi in alignment:
        t = t_lines[ti]
        if pi is None:
            s.failures.append({"truth": t.get("drug"), "problem": "line not found"})
            continue
        s.found += 1
        p = p_lines[pi]
        hits = field_hits(t, p)
        for k, ok in hits.items():
            s.fields[k] += int(ok)
        wrong = [k for k, ok in hits.items() if not ok]
        if wrong:
            s.failures.append(
                {
                    "truth": t.get("drug"),
                    "problem": "fields wrong: " + ", ".join(wrong),
                    "expected": {k: t.get(k) for k in wrong},
                    "got": {k: p.get(k) for k in wrong},
                }
            )
        if matches is not None:
            m = matches[pi] or {}
            got_key = (m.get("sku") or {}).get("composition_key")
            ok = bool(got_key) and norm_key(got_key) == norm_key(t.get("composition_key"))
            correct_by_pred[pi] = ok
            s.sku_correct += int(ok)
            if not ok:
                s.failures.append(
                    {
                        "truth": t.get("drug"),
                        "problem": "wrong SKU",
                        "expected": t.get("composition_key"),
                        "got": (m.get("sku") or {}).get("brand_name"),
                        "got_key": got_key,
                        "reranked": m.get("reranked"),
                        "reason": m.get("reason"),
                    }
                )
    if matches is not None:
        for pi, p in enumerate(p_lines):
            tri = triage(p, matches[pi])
            s.triage.append(tri)
            if tri == "green" and not correct_by_pred.get(pi, False):
                s.green_wrong += 1
    return s


def aggregate(scores: list[RxScore], latencies_ms: list[float], costs: list[float | None]) -> dict[str, Any]:
    n_truth = sum(s.truth_lines for s in scores) or 1
    out: dict[str, Any] = {
        "prescriptions": len(scores),
        "truth_lines": n_truth,
        "line_recall": sum(s.found for s in scores) / n_truth,
        "extra_lines": sum(s.extra for s in scores),
        "field_accuracy": {
            k: sum(s.fields.get(k, 0) for s in scores) / n_truth
            for k in ("drug", "strength", "doses_per_day", "duration_days", "quantity")
        },
        "p50_latency_ms": percentile(latencies_ms, 0.5),
        "p95_latency_ms": percentile(latencies_ms, 0.95),
        "mean_cost_usd": (sum(c for c in costs if c is not None) / len(costs))
        if costs and any(c is not None for c in costs)
        else None,
    }
    if scores and all(s.sku_evaluated for s in scores):
        items = [t for s in scores for t in s.triage]
        out["sku_match_accuracy"] = sum(s.sku_correct for s in scores) / n_truth
        out["pct_green"] = (items.count("green") / len(items)) if items else 0.0
        out["triage_counts"] = {k: items.count(k) for k in ("green", "amber", "red")}
        out["green_but_wrong"] = sum(s.green_wrong for s in scores)
    else:
        out["sku_match_accuracy"] = None
        out["pct_green"] = None
    return out
