"""List candidate salt-name aliases for a person to review. Never applies them.

    cd backend && PYTHONPATH=. uv run python ../scripts/etl/propose_aliases.py [--max-distance 2] [--min-common 50]

Reads the raw dataset (data/raw/indian_medicine_data.csv), normalizes every salt name
with the current rules, and prints rare names that sit within a small edit distance of a
common one, e.g. 'clinidipine' (3 rows) next to 'cilnidipine' (900 rows). Most hits are
different drugs that happen to be spelt alike (cefixime / cefepime, quinine / quinidine),
so folding them would be dangerous. This script only prints; a person decides, and adds
a true variant to SALT_ALIASES in backend/app/catalog/normalize.py by hand, together with
a test in backend/tests/catalog/test_normalize.py.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter

import pandas as pd
from common import RAW
from rapidfuzz.distance import Levenshtein
from rapidfuzz.process import extract

from app.catalog.normalize import SALT_ALIASES, parse_salt

RAW_CSV = RAW / "indian_medicine_data.csv"


def salt_counts() -> Counter[str]:
    df = pd.read_csv(RAW_CSV, usecols=["short_composition1", "short_composition2"])
    counts: Counter[str] = Counter()
    for part in pd.concat([df["short_composition1"], df["short_composition2"]]).dropna():
        salt = parse_salt(str(part))
        if salt is not None:
            counts[salt.name] += 1
    return counts


def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--max-distance", type=int, default=2, help="max Levenshtein distance")
    parser.add_argument("--min-common", type=int, default=50, help="rows needed to count as common")
    parser.add_argument("--max-rare", type=int, default=20, help="rows at most to count as rare")
    args = parser.parse_args(argv)

    counts = salt_counts()
    common = [name for name, n in counts.items() if n >= args.min_common]
    rare = sorted(name for name, n in counts.items() if n <= args.max_rare and name not in SALT_ALIASES)
    print(f"{len(counts)} salt names; {len(common)} common (>= {args.min_common} rows), {len(rare)} rare")
    print("REVIEW ONLY: nothing below is applied. Most pairs are different drugs.\n")
    print(f"{'rare name':<32} {'rows':>5}  {'common name':<32} {'rows':>6}  dist")
    found = 0
    for name in rare:
        matches = extract(
            name,
            common,
            scorer=Levenshtein.distance,
            score_cutoff=args.max_distance,
            limit=3,
        )
        for match, dist, _ in matches:
            if match == name or dist == 0:
                continue
            print(f"{name:<32} {counts[name]:>5}  {match:<32} {counts[match]:>6}  {int(dist)}")
            found += 1
    print(f"\n{found} candidate pairs. Add a true variant to SALT_ALIASES by hand, with a test.")


if __name__ == "__main__":
    main(sys.argv[1:])
