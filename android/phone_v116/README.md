# OKX Ai trade - 1.1.6

Replaces host-v13 (1.1.5) with host-v14. Trading source pins and configuration are unchanged. Only pure pattern/indicator/trend computations inside candidate packets are memoized. Packet freshness checks, current quotes, signal expiration, final admission, risk, orders and protection execute as before.

## Fix
1.1.5 phone measurements showed cache churn at the 32 MiB input budget (28,298 hits / 262,293 misses), and mean engine tick 7.65 seconds. This release keeps the latest generation per symbol/function/frame slot, interns identical complete serialized inputs with reference counts, and compares exact complete inputs on every reuse. Corrections and configuration changes invalidate results. Returned values remain isolated copies. Both entry count (4096) and unique input bytes (32 MiB) are bounded; this is not a bound on total Python process memory.

Admission exceptions have a separate bounded history; frequent closed-candle waits cannot overwrite it. Static category counts retain all occurrences. Raw exception messages are never recorded. The original closed-candle safety gate remains unchanged. Earlier unexplained admission errors cannot be diagnosed retroactively from these counters.

## Validation
Run with OKX_TEST_CORE pointing to the pinned Q2X runtime, websocket-client available and this directory on PYTHONPATH:

    python -m unittest test_signal_cache test_button_upgrade test_phone_mobile_integration test_performance test_followup test_predecessors -q

Tests cover 289 distinct synthetic series (300 bars per timeframe), 30 repeated rounds, all-symbol rollover and historical edits, a 64 KiB extra configuration value, original packet equality, historical positive-signal expiry, quote changes, copy isolation, memory reclamation, exception propagation and migration guards. test_signal_fixture.json is reused historical research data, not independent profitability validation. See validation.json for measured local results. Local packet timings are not Fold latency or a controlled live PC comparison. 1.1.5's previous benchmark reused only 60 distinct series; it did not validate the full working set.

## Installation and observation
Pause new entries in the mobile UI. Installation is deferred if positions, pending orders or conditional orders exist; it does not liquidate or cancel them. Check the new version and install from the same authenticated session. Refresh after installation, confirm 1.1.6, then explicitly resume trading if desired.

After 10 minutes:

    python -B ~/okx-phone/host-v14/phone_performance.py --brief

Actual phone speed and long-duration screen-off stability require post-install observation. No promise of zero network latency or improved trading profit is made.
