# Additional 1.6.10 repair

A queued protective close was removed before fallible per-position reconciliation. If reconciliation raised, the reason was lost but queued_risks continued blocking entry forever. At the exact queue-consumption point, the host now saves the already-issued close decision as close_requested before continuing. Journal failures requeue the event. No timeout clears risk markers or enables trading. A persisted user close reason is retained.

Validation adds an injected reconciliation failure followed by a durable-state reload, failed journal save/retry, and a 25-hour accelerated-clock engine run with real daily rollover and two simulated disconnections. The candidate function is stubbed in the clock test: this checks continuous scheduling/recovery, not 25 real hours on a phone or trading profitability. Existing entry conditions and strategy-specific time windows are unchanged. The UI separately reports scan age and current blocking state.

## Compact home balances

Daily PnL has a small signed percentage in brackets, divided by the first verified available balance recorded for that KST day. This display-only denominator is persisted across restarts and does not fluctuate when positions reserve margin. Older versions did not record historical available balance: the initial upgrade uses the first new observation and labels the amount and observation time; it does not invent an earlier day's available balance. A zero or missing denominator displays an em dash. Trading risk, daily-profit cash-flow adjustments and sizing are unchanged.

The former paid-AI-cost tile becomes the funding-account valuation, with an adjacent whole-account valuation tile. One independent read-only worker requests `GET /api/v5/asset/asset-valuation?ccy=USDT` every 15 seconds, backing off on errors. Both amounts come from the same exchange response, including other currencies converted by OKX; total includes trading, funding and Earn. Missing/error responses are not zero-filled or added to asynchronous trading values. Last known values remain visibly stale. The worker uses a separate client/session/clock and cannot write orders, transfers or account settings. Its values are never passed to trading admission or sizing.

Source: https://www.okx.com/docs-v5/en/#funding-account-rest-api-get-account-asset-valuation (checked 2026-11-17). Home cards use two main and three supporting tiles, reduced padding and smaller values. Full and streamed renders share the same updates; no DOM replacement of these values. Browser screenshots were not obtained in this restricted runtime; HTML generation and simulated-DOM behavior are covered by tests.

# Phone 1.6.10 — recover stale protection work; consider similar valid candidates

A confirmed position close could race a WebSocket callback that still held an old guard row. The callback re-added the closed client ID to `queued_risks`; subsequent ticks drained the event but could never clear the marker. This kept new entries and cooperative updates blocked. The host adapter now retires that ID only after successful original cleanup, removes only its queued events and ignores later callbacks for it. Other active risks survive. Entry cancellation is cleared only by the existing healthy account/protection recovery path; operator stops are preserved. Runtime diagnostics expose pending protection work counts.

The published 1.6.8 updater is preserved: busy handover is retried and can use a graceful serial pause/quit only if the user has already paused entries and both journal and exchange are flat, with no normal or conditional orders. Account and state checks occur before and after stopping; failed checks restore the prior service. A timeout, active owned position or uncertain protection cannot bypass handover. The separate 1.6.7 proven manual-reduction handover remains included. The installer makes read-only exchange requests.

## Similar candidates

The earliest still-held confirmed automatic position supplies an immutable snapshot of its entry confirmation candles. New candidates compare completed 15-minute candle shapes, EMA20 distance/slope, RSI14, Bollinger position, hourly EMA context and each symbol's volume relative to its own preceding 20 candles. No raw-volume comparison between differently sized coins is made. Missing entry snapshots on pre-update positions are reported, not reconstructed from the present chart.

The 0–100 score weights chart shape 40%, indicators 35%, and relative volume 25%. A score of at least 75 is a heuristic priority hint, not a calibrated probability, expected return or backtested profitable threshold. The UI shows at most three candidates in the existing stable scrolling diagnostics. Candidate labels distinguish original candle-condition passes from conditions still pending.

Only already valid common signals of the same direction can receive priority; older expiry buckets remain first. Original final rule revalidation, quote freshness, spread/depth/slippage, seen-signal checks, sizing and protection remain in force. No extra signals are manufactured and no low-similarity original signal is rejected. The reserved leader route retains its original priority. Capacity remains three common positions plus one shared trend/morning position. Similarity does not require opening multiple positions when original rules have not passed.

Repeated feature computation runs in the existing bounded background worker and exact-input cache. If a reserved-route signal is ready before publication, only that selected symbol takes one bounded local snapshot of the already available confirmation candles; it performs no API request or worker wait. Network/WS callbacks do not calculate indicators. The 148 pinned core sources, original signal predicates, entry hours, sizing and exit policies are unchanged. All previous installers remain immutable.

## Validation and limits

Run `PYTHONDONTWRITEBYTECODE=1 python android/phone_v1610_tests/run_validation.py`.

`validation.json` and `validation_logs/` record the exact results. Tests cover the close/callback race, failed cleanup, preservation of another active risk, recovery versus user pause, original admission rejection despite perfect similarity, scale-invariant relative volume, unfinished candles, frozen entry snapshots, three sequential common entries/fills/protection and the reserved fourth slot, paused-flat graceful update and restoration on failed checks, plus the inherited execution, manual reduction, transport, update and UI suites.

Trading tests use synthetic candles and a fake exchange with network disabled. Process tests use disposable local child processes. UI tests use a minimal DOM. These are not live phone observation, real exchange fills, a profitability backtest or proof of future entry frequency. No user diagnostic, account history or credentials are included in the release.

Host-v57 / service-57 / display 1.6.10; supported predecessor hosts 24–56.
