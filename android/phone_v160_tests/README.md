# Phone 1.6.0 — changing live leader

Run the offline suite from a disposable checkout (Python 3.12, requests,
websocket-client, python-dotenv, Node.js):

```sh
PYTHONDONTWRITEBYTECODE=1 python android/phone_v160_tests/run_validation.py
```

The runner reconstructs 148 hash-verified core files and previous host references
from the repository, builds the cumulative installer, and records each check in
`validation.json` with per-script output hashes. Exchange I/O is simulated;
actual engine entry, reconciliation and stop verification code is exercised.

## Changed behavior

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
Two JavaScript suites check DOM behavior and retained compact CSS. They do not
establish actual iPhone rendering or touch operation. No live phone install,
live exchange trade, uninterrupted connection guarantee or profitability
backtest is claimed by these results.
