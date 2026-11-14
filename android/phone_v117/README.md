# OKX Ai trade - 1.1.7

Consolidated Fold3 release. Direct upgrade from verified host-v13 (1.1.5) or host-v14 (1.1.6) to host-v15. The same 148 pinned Q2X source files and installed strategy configuration are preserved. This release adds no OR entry rule.

## Changes
- Retain the latest exact pattern/indicator/trend inputs per symbol/function/frame slot and share identical byte strings. Cache entries are bounded at 4096 and unique serialized input bytes at 32 MiB; this is not a limit on total Python memory. Compare complete inputs, including historical corrections/configuration changes, on every reuse. Return isolated result copies.
- Reuse presentation arrays only while the view revision is unchanged. New events publish immediately through the existing loop. Account age, controls, update ticket, performance summary and remote-access state remain fresh. Cache only three immutable asset responses per process.
- Invalidate public snapshots and reconnect when a text ping remains unanswered for 20 seconds. Preserve existing 20-second pings, reconnect backoff and resubscription. This is a recovery threshold, not a promise of zero network delay.
- Eliminate repeated construction of unchanged subscription pair sets using explicit watch revisions. Preserve the existing 2-second watch debounce and 10-second subscription operation spacing. Every incoming frame is still processed immediately.
- Display recent 30-tick mean/p95, cache hit/eviction counters, process RSS/CPU and the last admission exception on the mobile screen. Record bounded 10/30/60-minute checkpoints automatically using monotonic process elapsed time, including paused time. Keep entry/admission exception history separate from closed-candle waits. No raw exception messages or credentials are recorded.

Live quotes, completed-candle gates, signal expiry, account/risk checks, final order admission and protection remain active. There is no new REST polling, account-data caching, API rate-limit reduction, scheduler tuning or phone power-setting change.

## Validation
Run with OKX_TEST_CORE pointing to the pinned Q2X runtime and websocket-client / requests available:

    python -m unittest test_signal_cache test_button_upgrade test_phone_mobile_integration test_performance test_followup test_predecessors test_phone_transport test_fold_runtime -q

See validation.json and soak_cache.json for exact results. Tests cover actual pinned packet functions, 289 distinct synthetic series, warm reuse, all-symbol rollover, old-candle corrections, large configuration changes, positive-signal expiry, quote changes, isolated returned values, generation/reconnect behavior, paused/flat migration and UI freshness/security. The historical signal fixture is reused research data, not independent profitability validation.

The accelerated offline repeat test ran 289 symbols x 201 rounds = 58,089 packets, with concurrent diagnostics. After warmup it produced no additional cache misses or evictions; input bytes stayed at 8,394,965 and process RSS at 62.3–62.5 MiB. These are Linux test-process measurements, not Fold3 engine latency, device RAM use or battery/thermal results. The previous 1.1.5 benchmark repeated only 60 distinct series and did not exercise the full working set.

## Installation
On the same authenticated mobile session: pause new entries, check the new version, install 1.1.7, refresh and verify the version. Then explicitly resume trading if desired. Installation is deferred while exchange positions, pending/conditional orders or unresolved owned records exist; it does not cancel or liquidate them. Predecessor files are verified, shutdown is graceful, account state is rechecked, and a failed readiness check attempts rollback in the paused state.

No Termux command is needed for routine diagnostics after installation. Activity/settings shows the measurements; the three automatic checkpoint files are stored in the phone root. Actual Fold3 speed, heat and long-duration screen-off behavior remain to be observed. Android power policy and network availability cannot be guaranteed by this update.
