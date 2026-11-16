# Phone 1.6.3 — consistent live candles and stable diagnostic controls

A later REST candle response could replace the forming candle while the price
badge continued showing a fresh WebSocket quote. Both now use the same fresh
quote during the same paint. For example, a REST close of 100 received after a
live price of 103 now displays a forming close and badge of 103. Official open,
volume and confirmation are retained. Confirmed candles and missing rollover
candles are never rewritten or invented.

When the chart is panned into history, the current-price badge is hidden rather
than being drawn against an older final candle. A compact `현재 봉으로` button
restores the latest window and normal vertical scale. User navigation is otherwise
preserved. The selected timeframe's remaining-time label is retained.

## Reception and display work

- The selected chart lazily opens one display-only, ticker-only public connection
  using the existing TLS, reconnect, generation, freshness and subscription-budget
  implementation. It no longer has to read a quote behind the 290-symbol monitor
  once that selected-symbol quote is available. The requested watch is replaced
  on selection changes; it is not an ever-growing union. Removed subscriptions
  drain within the existing rate limits. After 15 seconds without quote consumers,
  the watch is cleared and the connection closed. Closing the host stops it.
- This lane never supplies strategy prices, entry admission, stop prices, PnL or
  private-account values. The existing stream is a fresh display fallback while
  the selected lane warms up or reconnects. No exchange REST polling is increased.
- Chart SSE advertises a 500 ms reconnect interval and retains the 250 ms send
  target. These are scheduling targets, not measured phone/network latency.
- The existing ranking publisher now supplies an immutable display snapshot.
  Mobile capture does not collect ranking data while holding the display lock.
  A deliberately blocked ranking collection cannot block chart or account reads.
  Strategy ranking and the final leader/freshness checks remain unchanged.
- Each candle REST response now publishes one full-history event rather than
  identical early/final events. Direction analysis stays on its independent
  worker; candle polling, error reporting and confirmation rules are retained.
- Diagnostic exports include the selected display lane's connection, quote age,
  frame count and disconnect count to support a subsequent real-phone check.

## Stable settings layout

Update notes, performance text, diagnostic content, save status and calculation
status have fixed-height internal scroll regions. The save button is a persistent
node outside the changing diagnostic body. Rendering does not replace its pending
state or click handler. Diagnostic scroll positions are retained; repeated errors
replace the status text instead of adding paragraphs below the button. The existing
compact position and one-line strategy layouts are unchanged.

## Validation

```sh
PYTHONDONTWRITEBYTECODE=1 python android/phone_v163_tests/run_validation.py
```

Requires Python 3.12 with requests, websocket-client and python-dotenv, plus Node.js.
The runner reconstructs 148 hash-verified core files and previous host references
from repository artifacts. It builds the cumulative installer and records test
outputs and hashes in `validation.json` and `validation_logs/`.

The recorded run passed **309 Python tests and four JavaScript suites**. New checks
cover late REST/quote races, current/historical price presentation, a blocked
whole-market reader, lazy selected subscriptions, idle release/reconnect,
generation and freshness rejection, duplicate candle publication, nonblocking
display capture, and stable diagnostic button identity/scroll/pending state.
The final compiled chart was also rendered with a native Canvas implementation:
the simulated final candle closed at the displayed 0.010396 price with 07:58 left.

Inherited checks exercise actual strategy, engine, fill reconciliation and stop
verification functions with fake exchange I/O, including position-preserving
upgrade/rollback and historical host migrations. There were **zero actual exchange
order requests**. UI checks use a minimal DOM and native Canvas, not an actual
phone browser. No profitability backtest or sustained phone-latency measurement
was performed.

## Scope and remaining evidence limits

The supplied 1.6.2 diagnostic recorded one monitoring-lane EOF/recovery and no
execution-lane disconnect during that run. Its monitor heartbeat round-trip was
longer than the execution lane's. Those observations do not establish whether
the EOF was caused by CPU contention, Wi-Fi, server behavior or another cause.
This release isolates display traffic and removes identifiable redundant/blocked
display work; it does not claim to eliminate all network disconnects.

Entry patterns, windows, sizes, the shared-three plus reserved-one allocation,
order/SL/exit management, credentials and the 148 pinned core files are unchanged.
Prior installers remain immutable. This is host-v50/service-50, cumulatively
upgradeable from hosts 24–49, using the existing position-preserving handover and
checksum-verified previous-host restoration.
