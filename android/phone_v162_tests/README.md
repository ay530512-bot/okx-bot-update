# Phone 1.6.2 — live account display, candle timer and compact rules

Run the offline suite from a disposable checkout (Python 3.12, requests,
websocket-client, python-dotenv, Node.js):

```sh
PYTHONDONTWRITEBYTECODE=1 python android/phone_v162_tests/run_validation.py
```

The runner reconstructs 148 hash-verified core files and previous host references
from the repository, builds the cumulative installer, and records each check in
`validation.json` with per-script output hashes. Exchange I/O is simulated;
actual engine entry, reconciliation and stop verification code is exercised.

## Changed behavior

This cumulative installer includes 1.6.0 live leader selection and 1.6.1 chart
streaming. New behavior in 1.6.2:

- Received USDT account equity, available balance and matching position values
  are projected into a read-only mobile snapshot immediately after the original
  private account callback. The dashboard no longer waits for the entire engine
  scan to finish before showing these received values. Public prices never
  synthesize money or PnL. Daily PnL uses the last reconciled cash-flow baseline;
  the screen labels that basis. A new KST day waits for its new baseline.
- Same-origin authenticated dashboard SSE sends changed fields at a 250 ms
  target cadence, with a bounded 500 ms cache-only JSON fallback. Full dashboard
  refresh is reduced to once every two seconds. Home packets omit the full
  market list and diagnostic histories. Neither path introduces an exchange
  connection or changes exchange REST polling.
- Repeated position and market updates retain existing DOM nodes and replace
  changed numeric text. Expanded position evidence, close-button identities,
  scroll position and chart navigation are retained. Hidden market/activity/
  diagnostic panels are not rerendered. Rendering is coalesced by animation frame.
- Private display values expire after five seconds and require the current
  connection generation. Older events cannot overwrite newer observations.
  Quantity or entry-price changes wait for authoritative reconciliation rather
  than mixing a partial-close observation with the old holding. Disconnects
  disable stale trading controls. Display arrivals never freshen order gates,
  account reconciliation timestamps, strategy or risk inputs.
- A small right-axis box shows the received current price and remaining candle
  time. It follows the selected 1m/5m/15m/1H/4H/1D/1W frame and updates once per
  second from the packet's server time. It requires an official current forming
  candle; missing rollover data says `봉 대기` rather than inventing a candle.
- Each of the five top rules now has one line: rule name, time and short
  condition. Row spacing and notice padding are smaller. Narrow screens retain
  horizontal overflow instead of wrapping the rules into multiple lines.

The inherited display-only chart path is:

- The selected chart receives authenticated same-origin SSE packets every
  250 ms from the existing public WebSocket cache. Packets contain the latest
  quote and two candle rows. There is no new exchange connection in trading
  mode, no extra REST request per packet, and no strategy/position-price input
  from this display path. If SSE is unavailable, a bounded 500 ms JSON fallback
  reads the same cache. These are refresh targets, not network latency promises.
- Fresh received ticker prices update the current-price line and the forming
  candle. Official candles retain their opening price, volume and confirmation.
  Existing stream-collected extremes are used for 5m/15m/1H/4H; other frames
  combine sampled quotes and official REST updates. Missing rollover candles
  are not invented. Old/disconnected quotes are marked unavailable.
- Candle retrieval keeps its one-second cadence but requests two rows from a
  warm cache instead of 300. Initial loads and gaps load 300; older-history
  pagination is retained. Direction analysis runs independently, coalesced at
  five-second intervals, so a slow analysis request cannot stall candle reads.
- Full chart snapshots are fetched every five seconds. A symbol/frame change
  aborts the old full request; late responses cannot replace the new selection.
  Live merges preserve pan, zoom and historical anchors. Drawing is coalesced
  through requestAnimationFrame; unchanged canvas dimensions are retained.
  Streams and drawing stop while the chart is hidden.
- REST failures retain the last chart with its original observation timestamp.
  Display-only quote arrivals never refresh manual-entry analysis timestamps.
  The SSE endpoint checks host, login and session expiry and caps concurrent
  streams. No manual entry/close or automatic trading controls are changed.

The inherited live-leader behavior is:

- One shared KST09 opening-price/current-price ranking covers every permitted
  instrument, continuously, including entry-paused/full-position states.
- The existing full-market REST cache and monitoring WebSocket supply prices.
  The duplicate mobile REST feed is removed. Cached ranking refreshes at most
  once per second; final entry validation bypasses that cache. No new REST
  requests or candle fetches are introduced by ranking.
- A changed leader is evaluated within the same 15-minute/hourly interval.
  Old-symbol arms and pending signals are invalidated. Entry admission checks
  the leader again after REST candle validation and after final risk checks.
- KST15:00–next02:00 long entries and KST05:00–08:00 short entries retain their
  exact existing boundaries. KST02:00–05:00 tracks/prewarms the new leader as
  the upcoming short target, without placing an early entry.
- A newly selected long leader is checked using its completed breakout/pullback
  setup in the current long session. Earlier confirmations are consumed; only
  the latest completed candle can produce a signal, with its original 90-second
  deadline. Brief data gaps may reconstruct that same unexpired setup, never
  restart its lifetime. Signal identities/processed-signal guards are retained.
- Ranking requires complete current-price coverage, not every instrument's
  hourly candles. The chosen long still requires its confirmed 15m/1H candles;
  the chosen short still requires its confirmed 15m pattern. Missing data never
  substitutes the second-place coin. Verified post09 listings remain excluded
  until the next KST09 baseline exists.
- The screen's leader and inspection target use the same snapshot. Outside
  entry windows the screen names the upcoming target and entry start time.
  Old position evidence retains its historical completed-hour ranking label;
  new evidence explicitly says current-price ranking.

Existing candle predicates, leverage, position size, slot limits, expiry,
liquidity gates, duplicate prevention, SL and holding-management functions are
preserved. Rank changes alone do not close a holding. The existing qualified
reserved-long-to-morning-short transition still requires a confirmed full close
and protection cleanup before any short order.

The compact position layout is retained; its numeric update implementation is
now incremental. Cooperative protected position handover remains in place.
The inherited legacy-updater regression fix
captures user entry intent after slow preflight account reads, so a user stop
recorded during those reads cannot be mistaken for the installer's own pause.

## Evidence and limits

`test_live_rank.py` covers same-bar leader changes, late pre-order changes,
current leader tracking after02/at05, stale/incomplete quotes, new listings,
selected candle availability, duplicate/expiry guards, and real engine simulated
order/fill/protection paths. It also measures 290-symbol ranking locally with
zero REST requests. That timing is not Fold3 hardware performance.

The inherited suites exercise all eight rule/direction entry paths, four compute
workers, socket recovery simulations, holding/protection, close-to-short
reconciliation, immutable packaging and real disposable Linux updater processes.
`test_chart_live.py` additionally holds an analysis request open while checking
that candle polling continues, and covers generation/freshness, candle rollover,
canonical OHLCV, authenticated SSE, bounded sessions and REST failures.
`test_chart_ui.cjs` exercises selection races, reconnection fallback, late
responses, quote freshness, live/history merging, retained navigation and the
actual combined Canvas renderer with a simulated canvas. It also syntax-checks
the final combined JavaScript asset.

`test_dashboard_live.py` verifies original-callback ordering, actual account
fields, baseline/day handling, strict position identity, disconnect/generation
changes, freshness, malformed values, bounded cache, packet scope and authenticated
SSE. `test_dashboard_ui.cjs` covers a blocked full snapshot while fast updates
continue, late-response ordering, unchanged stale-order gates, frame coalescing,
hidden-panel work, page/stream transitions, fallback limits and retained market
nodes. Position tests also check card identity across price changes. Chart tests
check countdowns across supported frames, close boundaries and marker placement.

The recorded run passed 299 Python tests and four JavaScript suites. JavaScript
tests use a minimal DOM. A separate visual check drew the final compiled chart
with native Canvas, simulated candles and the requested `0.010396 / 07:58` marker.
These checks do not establish actual iPhone rendering, touch operation or Fold3
CPU/latency. No live phone install, live exchange trade, uninterrupted connection
guarantee or profitability backtest is claimed by these results. The 250 ms
cadence is a transmission target, not an end-to-end latency guarantee.
