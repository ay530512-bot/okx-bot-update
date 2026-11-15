# 1.2.5 CPU overhead reduction

Changes: freeze newly merged completed candle arrays once, reuse their exact serialized bytes, and retain full invalidation on every new/corrected input. Mutable/unusual inputs retain the original path. Positive and manual packets retain original list shapes. Fresh quote, expiry, generation and final admission checks remain live. Public quote processing avoids rebuilding unchanged OHLC values and uses equivalent finite-price extrema comparisons; every quote timestamp and mark callback is retained.

No symbol reduction, scan interval increase, signal threshold change or new order worker. The 1.2.4 public socket/heartbeat/recovery implementation is byte-identical. Account, sizing, handover and pinned strategy files are preserved. Quarter-sized trend-pullback longs remain as approved.

## Validation

82 offline Python tests and 3 diagnostic DOM scenarios passed. Includes real pinned candidate/stream readers, immutable producer integration, corrected historical candles, expiry during scans, stale/future/prior-generation quotes, sizing, protection handover, updater rollback and the real 1.2.4 button's compatibility with the new installer. Exchange responses/process boundaries are fixtures or mocks; no actual orders were sent.

Offline CPU comparison against 1.2.4, same workstation, 289 fixture/synthetic symbols, five trials of 30 warm scans:

| Measured path | 1.2.4 median CPU time | 1.2.5 median CPU time | Reduction |
|---|---:|---:|---:|
| One warm 289-symbol scan | 0.034233 s | 0.008424 s | 75.39% |
| 30,000 repeated-price ticker frames | 0.14330 s | 0.10572 s | 26.23% |
| 30,000 changing-price ticker frames | 0.13540 s | 0.11964 s | 11.64% |

Signal result hashes and final OHLC state hashes agree. These are component CPU times excluding network/account waits, not Fold CPU percentage or end-to-end latency. Cold snapshot preparation still costs work at data arrival. No actual phone thermal/battery, sustained connection, fill or protective-order placement verification is claimed.

`benchmark_host22.json` and `benchmark_host23.json` contain all final trial values. `validation.json` records code hashes, implementation/test issues corrected during development, and limits. `test_results.txt` records final commands and outputs.

## Reproduce

Use the pinned core archive SHA256 `6b2a0a90f02cca914ffc5cc0996555e8c1435b7a61618575ee94ee2ebdc2dad1`, unpacked in sibling `core121`, with previous installers staged in sibling `fixture121`. `build_release.py` verifies the 1.2.4 predecessor and stages host-v23 without starting services. Use websocket-client 1.8.0 (`/tmp/okx123deps` in this validation environment).

Run `python -B android/phone_v125/build_release.py`, then `python -B android/phone_v125/run_validation.py`. For benchmark reruns set `OKX_TEST_CORE` to the core directory and `OKX_TEST_HOST` to host-v22 or host-v23, and run `benchmark_cpu.py` separately for each. No live endpoint is contacted by those tests.

Delivery: version 23 / display 1.2.5, predecessor version 22 only. Existing safe serial handover is retained; uncertain protection or pending execution defers handover. This release does not claim to eliminate EOF disconnections or guarantee entries/profit.
