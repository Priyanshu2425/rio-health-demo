# Handwritten set

Ten real prescriptions written by hand and photographed with a phone, reported separately
from the synthetic set. `eval/run.py` skips this set while it is empty.

## What to drop here

- `hw_01.jpg` … `hw_10.jpg`: one prescription per photo, taken the way a customer would
  (a phone photo on a table, not a scan). JPEG, PNG or WebP, under 5 MB each.
- Write them like a real Indian prescription: a letterhead or doctor name, patient name
  and date, then 2–5 lines such as `Tab. Augmentin 625  1-0-1 x 5 days`. Use real brands
  that are in the catalog (`data/seed/` once loaded), mix notations (`1-0-1`, `BD`, `TDS`,
  `SOS`, `5/7`), and include at least one struck-through line and one hard-to-read word.
- Don't include real patient data.

## Truth files

Each image needs `hw_NN.truth.json` next to it:

```json
{
  "lines": [
    {"drug": "Augmentin", "strength": "625", "doses_per_day": 2, "duration_days": 5,
     "quantity": null, "composition_key": "amoxycillin 500mg + clavulanic acid 125mg"}
  ]
}
```

- `drug`: the name as written, without form or strength.
- `strength`: as written (`"625"`, `"500 mg"`), or `null` if none is written.
- `doses_per_day`: `1-0-1` → 2, `TDS` → 3, `SOS` → `null`.
- `duration_days`: `x 5 days` or `5/7` → 5, `2/52` → 14; `null` if not written.
- `quantity`: only an explicit count written on the paper, in dispensable units: tablets
  or capsules for solid forms (`#10` → 10), bottles, tubes or sachets otherwise
  (`1 bottle` → 1). `null` if not written or written as strips/packs (`2 strips`).
- `composition_key`: the catalog's key for the intended SKU (the `composition_key`
  column of `skus`). Leave out struck-through lines.

You don't have to type these from scratch. After adding the images, run

```sh
cd backend && uv run python ../eval/prefill_handwritten.py --model <VISION_MODEL>
```

It writes each truth file from the model's parse and marks it `"_prefilled": true`.
Correct every field against the paper, then delete the `_prefilled` and `_prefilled_by`
lines. `run.py` ignores truth files that are still marked, so an unchecked prefill never
counts as ground truth.

When one of these replaces the handwritten-style demo sample, copy it to
`backend/app/parser/samples/`, add it to `manifest.json`, and run
`eval/refresh_samples.py`.
