# Phone 1.6.1 — live chart updates and changing leader

Run the offline suite from a disposable checkout (Python 3.12, requests,
websocket-client, python-dotenv, Node.js):

```sh
PYTHONDONTWRITEBYTECODE=1 python android/phone_v161_tests/run_validation.py
```

The runner reconstructs 148 hash-verified core files and previous host references
from the repository, builds the cumulative installer, and records each check in
`validation.json` with per-script output hashes. Exchange I/O is simulated;
actual engine entry, reconciliation and stop verification code is exercised.

## Changed behavior

The cumulative installer includes the complete 1.6.0 leader update below.
This version adds a display-only chart path:

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

The compact 1.5.6 stylesheet and position UI are unchanged. Cooperative protected
position handover remains in place. An additional legacy-updater regression fix
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

Three JavaScript suites check DOM behavior and retained compact CSS. They do not
establish actual iPhone rendering or touch operation. No live phone install,
live exchange trade, uninterrupted connection guarantee or profitability
backtest is claimed by these results.
