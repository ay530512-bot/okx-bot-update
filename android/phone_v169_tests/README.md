# Phone 1.6.9 — recover stale protection work; consider similar valid candidates

A confirmed position close could race a WebSocket callback that still held an old guard row. The callback re-added the closed client ID to `queued_risks`; subsequent ticks drained the event but could never clear the marker. This kept new entries and cooperative updates blocked. The host adapter now retires that ID only after successful original cleanup, removes only its queued events and ignores later callbacks for it. Other active risks survive. Entry cancellation is cleared only by the existing healthy account/protection recovery path; operator stops are preserved. Runtime diagnostics expose pending protection work counts.

The published 1.6.8 updater is preserved: busy handover is retried and can use a graceful serial pause/quit only if the user has already paused entries and both journal and exchange are flat, with no normal or conditional orders. Account and state checks occur before and after stopping; failed checks restore the prior service. A timeout, active owned position or uncertain protection cannot bypass handover. The separate 1.6.7 proven manual-reduction handover remains included. The installer makes read-only exchange requests.

## Similar candidates

The earliest still-held confirmed automatic position supplies an immutable snapshot of its entry confirmation candles. New candidates compare completed 15-minute candle shapes, EMA20 distance/slope, RSI14, Bollinger position, hourly EMA context and each symbol's volume relative to its own preceding 20 candles. No raw-volume comparison between differently sized coins is made. Missing entry snapshots on pre-update positions are reported, not reconstructed from the present chart.

The 0–100 score weights chart shape 40%, indicators 35%, and relative volume 25%. A score of at least 75 is a heuristic priority hint, not a calibrated probability, expected return or backtested profitable threshold. The UI shows at most three candidates in the existing stable scrolling diagnostics. Candidate labels distinguish original candle-condition passes from conditions still pending.

Only already valid common signals of the same direction can receive priority; older expiry buckets remain first. Original final rule revalidation, quote freshness, spread/depth/slippage, seen-signal checks, sizing and protection remain in force. No extra signals are manufactured and no low-similarity original signal is rejected. The reserved leader route retains its original priority. Capacity remains three common positions plus one shared trend/morning position. Similarity does not require opening multiple positions when original rules have not passed.

Repeated feature computation runs in the existing bounded background worker and exact-input cache. If a reserved-route signal is ready before publication, only that selected symbol takes one bounded local snapshot of the already available confirmation candles; it performs no API request or worker wait. Network/WS callbacks do not calculate indicators. The 148 pinned core sources, original signal predicates, entry hours, sizing and exit policies are unchanged. All previous installers remain immutable.

## Validation and limits

Run `PYTHONDONTWRITEBYTECODE=1 python android/phone_v169_tests/run_validation.py`.

`validation.json` and `validation_logs/` record the exact results. Tests cover the close/callback race, failed cleanup, preservation of another active risk, recovery versus user pause, original admission rejection despite perfect similarity, scale-invariant relative volume, unfinished candles, frozen entry snapshots, three sequential common entries/fills/protection and the reserved fourth slot, paused-flat graceful update and restoration on failed checks, plus the inherited execution, manual reduction, transport, update and UI suites.

Trading tests use synthetic candles and a fake exchange with network disabled. Process tests use disposable local child processes. UI tests use a minimal DOM. These are not live phone observation, real exchange fills, a profitability backtest or proof of future entry frequency. No user diagnostic, account history or credentials are included in the release.

Host-v55 / service-55 / display 1.6.9; supported predecessor hosts 24–55.
