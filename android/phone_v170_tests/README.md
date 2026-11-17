# Phone 1.7.0: existing trend entry OR EMA20 support rebound

The existing top-gainer breakout/dip predicates and their held-position management are unchanged. The serialized coordinator also evaluates an independent long entry for the current KST09-relative top gainer at rising 15-minute EMA20 support. Both paths share the existing reserved slot, entry window (KST15:00–next02:00), 5x sizing and protective management.

## Added entry evidence

- Closed-bar path: the previous close was above its EMA20, the latest candle's low touched the EMA band, and the candle closed bullish above a rising EMA20. Only the original close + 90 seconds is valid.
- Live path: with the latest closed candle above a rising EMA20, an actually received current-bar price touches or crosses below that EMA; a later timestamped price recovers above it. The signal starts at observation of the recovery; it does not wait for the 15-minute close. An initial price already above EMA is not invented as a touch.
- The EMA calculation uses a fixed 55-closed-bar prefix and an initial 20-close SMA seed. REST revalidation uses the identical prefix. This avoids cache/REST history-length disagreement; it is not a claim to match a venue chart initialized from different history.
- No additional breakout or closed-hour MA50 filter is imposed on the added branch. The existing branch still requires its own original conditions.
- A live signal's completed-bar similarity reference is frozen at its last completed candle, not at a fabricated candle close.

A candidate must still pass the original complete-universe leader check, fresh execution quotes, liquidity/spread, original price/slippage bounds, margin and fee reserve, same-symbol exclusion, position capacity, expiry, and protective-order checks. Leader changes discard the previous leader's pending support. Identity/expiry survives restart and leader churn. This update does not retrospectively enter expired patterns.

Existing automatic/manual reductions, legacy trend/morning exits, and all other position policies remain in place. In particular this entry-only OR change does **not** introduce a different partial-take-profit or volume-red-candle exit policy.

The UI shows both trend paths, EMA20, and the symbol/route passed to final admission. Live recovery timestamps are identified separately from closed-candle timestamps. Update version 1.7.0 reflects a strategy addition; prior supported hosts are 24–58.

## Validation

Run `PYTHONDONTWRITEBYTECODE=1 python android/phone_v170_tests/run_validation.py` from the repository root. `prepare_tests.py` reconstructs and verifies the pinned baseline without external downloads. The exchange and sockets are simulated and trading network calls are blocked. `validation.json` and the scenario reports contain the actual results.

New cases cover both support paths, no-touch/no-recovery, stale/future prices, unchanged breakout rejection with successful OR fallback, leader churn, changed candles, original expiry, full serialized order/fill/SL confirmation, manual partial-close management, and guarded fourth-slot admission. The fourth slot still requires fee headroom: a test confirms rejection at insufficient available margin, then successful fourth-position admission after a confirmed manual partial reduction releases margin.

Some inherited candle fixtures also meet the newly added support rule. In tests specifically exercising the original common routes, synthetic KST09 quote baselines make those instruments non-leaders; their candle predicates, order assertions and risk checks remain unchanged. Dedicated new cases exercise overlapping/fallback candidates and reserved priority.

No actual phone runtime, real exchange fill, strategy profitability, or the user's BTW 2026-11-17 event has been verified by these offline tests. The supplied chart displays MA values, not an EMA20 series. No original BTW candle sequence or contemporaneous diagnostic export was available for a causal replay of that specific missed entry.
