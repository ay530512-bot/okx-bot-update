# Phone 1.7.1: withdraw EMA entry and prepare public connection rollovers

This cumulative update supports hosts 24–59, including installed 1.6.11 and 1.7.0.
It removes the newly added EMA20 OR entry from the serialized coordinator and
rejects persisted/direct EMA entry requests. The original trend-long source,
morning-short/switch source, sizing, exit policy, and manual reduction/risk
management sources are byte-identical to 1.7.0. Previously opened EMA positions
retain their recorded reserved-slot management; no position is closed by this
installer. The home/diagnostic labels stop advertising the removed entry.

## Public connection handling

The supplied six-hour diagnostic identified ten monitor interruptions and one
execution-stream interruption. Both lanes received OKX service-upgrade notice
64008 before one simultaneous EOF. Other monitor EOFs occurred with recently
received frames/pongs; their remote/network cause is not established by that
export. The exception named spread_check is an order-admission spread rejection,
not evidence of a websocket disconnect. No raw diagnostic/account data is shipped.

On 64008, the active public reader now continues receiving while one temporary
worker connects to the same verified TLS endpoint, subscribes the same desired
pairs and checks acknowledgments plus fresh non-trade snapshots. The active
reader alone adopts the replacement. The worker stops reading before adoption;
quotes retain original receive times and receive a new generation. Old quotes
and old band caches are never promoted. The ordinary per-channel trade-age,
exchange-time, liquidity and account recovery guards remain in force. A quiet
trades channel is not fabricated to make admission pass.

Failures, stale warm data, changed watches, stop/manual reconnect and a second
upgrade notice reject the replacement. A failed attempt leaves the working
connection intact and waits ten seconds before another attempt. Socket cleanup
does not block the owner's state lock. Monitor handover does not reset the
execution stream. Planned replacement counts are displayed separately from
actual disconnect counts; the latter are not erased or relabeled.

After a remotely closed healthy connection (at least 30 seconds uptime and a
frame in the last 5 seconds), reconnect delay is 0.25 seconds rather than the
old 2 seconds. This is the wait **before** DNS/TCP/TLS/subscriptions, not a claim
that complete recovery takes 0.25 seconds. Early/handshake failures still use
exponential backoff. Diagnostics now retain numeric HTTP handshake status and
connection-reestablishment duration.

No claim is made that all EOF root causes or phone/network outages are fixed.
A long-running physical Fold3/OKX session was unavailable for validation here.
The change does not sample/drop market ticks or reduce the monitored universe;
CPU consumption and unannounced remote EOF still need field measurement.

## Reproduction

Run `PYTHONDONTWRITEBYTECODE=1 python android/phone_v171_tests/run_validation.py`.
The reference core is reconstructed from pinned local archives. Tests exercise
fake websocket frames and fake exchange I/O, prohibit live orders, and include
rollover readiness/races, EOF retry pacing, existing strategies/short switching,
position protection, update handover and UI regression tests.

The old positive EMA-entry tests are replaced by removal/legacy-record tests.
`make_legacy_support_fixture.py` separately executes the 1.7.0 fake-exchange
harness to capture an actual prior-runtime filled and SL-confirmed EMA record.
1.7.1 restores that record, proves read-only handover, applies a simulated manual
half reduction, and verifies retained ownership/protection without opening a
new order. Remaining rules keep full dynamic entry/fill/SL coverage.

Source reference: https://www.okx.com/docs-v5/en/ (WebSocket notification 64008).
