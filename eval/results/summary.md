# Eval summary

Appended by `eval/run.py`. Recall, field and SKU accuracy are over truth lines; % green is
over parsed lines; latency is parse + match per prescription; cost is per prescription.

| When (UTC) | Set | Vision model | Re-rank model | Rx | Line recall | Drug | Strength | Doses/day | Days | SKU match | Green | Green but wrong | p50 | p95 | $/Rx |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-09-30 08:54 | synth | `oracle` | `-` | 20 | 100% | 100% | 100% | 100% | 100% | **100%** | 60% | 0 | 1.4 s | 1.9 s | $0.0000 |
| 2026-09-30 11:25 | synth | `oracle` | `openai/gpt-6-luna` | 20 | 100% | 100% | 100% | 100% | 100% | **100%** | 77% | 0 | 4.0 s | 7.0 s | $0.0001 |
| 2026-09-30 11:27 | synth | `google/gemini-3.8-flash` | `openai/gpt-6-luna` | 20 | 91% | 91% | 91% | 91% | 91% | **n/a** | n/a | n/a | 14.0 s | 23.1 s | $0.0067 |
| 2026-09-30 11:35 | synth | `google/gemini-3.8-flash` | `openai/gpt-6-luna` | 20 | 100% | 100% | 100% | 100% | 100% | **100%** | 71% | 0 | 14.0 s | 23.1 s | $0.0074 |
