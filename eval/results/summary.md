# Eval summary

Appended by `eval/run.py`. Recall, field and SKU accuracy are over truth lines; % green is
over parsed lines; latency is parse + match per prescription; cost is per prescription.

| When (UTC) | Set | Vision model | Re-rank model | Rx | Line recall | Drug | Strength | Doses/day | Days | SKU match | Green | Green but wrong | p50 | p95 | $/Rx |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-09-30 08:54 | synth | `oracle` | `-` | 20 | 100% | 100% | 100% | 100% | 100% | **100%** | 60% | 0 | 1.4 s | 1.9 s | $0.0000 |
