# OKX Ai trade - 1.1.4

Phone-only minor performance update. Trading rules, risk and admission checks unchanged.

Adds exact-input bounded memoization of pure `okx_two_wick732.select`, `okx_band_flow.view` and `okx_pattern15.summary` only while constructing candidate packets, after the five baseline ticks. SHA-256 of full serialized input values keys each entry; full config for view is included. Misses compute on the serialized snapshot. Return values are copied so caller evidence cannot corrupt the cache. Maximum4096 entries. No stored API responses, credentials, quotes, orders or complete time-sensitive decisions. Cache is memory-only and resets on restart.

Packet freshness validation, new completed candle selection, evidence time, signal expiry, live quote checks, and original check_entry remain executed. Calls outside packet scope bypass cache, including final admission and protection. Source hashes must match pinned core. Does not alter API limits, scan coverage or loop cadence. New candles and historical corrections produce different keys.

All prior 1.1.3 account-read guards retained. Compatible with exact host-v11 only. Updater requires paused, flat account and verifies it again before/after graceful stop. User starts live trading explicitly. No automatic liquidation/cancellation.

## Reproduce
Set OKX_TEST_CORE to pinned Q2X runtime matching phone_sources.json; install its dependencies. Run:
`python -m unittest test_signal_cache test_button_upgrade test_phone_mobile_integration test_performance -q`
`python build_phone_button.py`

22 tests include historical positive OP signal fixture, synthetic packets, identical outputs, caller mutation, full-input invalidation, candle boundary, signal expiry and bypass of admission setup. Historical fixture is preserved prior research data, not independent profitability validation. Synthetic289 warm repeated-packet benchmark is local only and not a Fold speed guarantee. No live orders executed.

After installing, performance JSON includes signal_cache hits/misses and signal.pattern/indicators/trend compute/key/reuse timings. Inspect using `python -B ~/okx-phone/host-v12/phone_performance.py`. Cold first use recomputes. Different live baseline/optimized workloads cannot establish causal speed gains.

Version digits: major product / trading-rule / minor performance or design. This release is1.1.4. PC release not changed.
