# Phone 1.6.4 — monitoring reads and a stable two-line home status

The home receipt/reconciliation status used to wrap as its text changed and move
the controls below it. It now has two explicit rows in a fixed-height region:
balance receipt plus order reconciliation ages, then the PnL basis plus display
refresh status. Digits have tabular spacing. Unusually long content scrolls
horizontally inside the region instead of adding vertical rows.

## Monitoring reception

The monitoring connection now reads up to 16 KiB of already-available TLS data
and serves the frame parser's small reads from that bounded buffer. A short
read returns immediately; it never waits to fill the buffer. All WebSocket
messages still pass through the existing parser and ticker feed in order.
No ticks are sampled away, and there is no change to freshness requirements,
frame validation, heartbeat deadlines, reconnection or subscription budgets.
The execution connection retains its previous exact-size read behavior.
Changing or closing the underlying socket invalidates buffered bytes.

The supplied 1.6.2 diagnostic recorded a monitoring EOF at 03:58:13 KST on
November 17, after about 172 seconds connected. The last frame was received
0.002 seconds before that EOF. This was not a locally detected idle timeout.
It does not establish whether CPU contention, Wi-Fi or the remote peer caused
the closure. This change reduces identifiable receive work; it does not prove
that the reported EOF cannot recur.

## Connection evidence

Monitoring-only disconnects and recoveries now participate in the connection
trace's change signature. Previously the detailed event list could miss those
changes when execution and account connections stayed unchanged.

Five-second samples retain monitoring frame/heartbeat state, latest received
quote age, observer delay and host-process CPU usage (one-core percentage).
Quote lag uses the already-present server clock anchor; this observer never
performs a network clock sync. Lag combines quote age, transport/processing
delay and clock uncertainty; it is not a pure network latency measurement.
The sampled host CPU is not the sum of all phone processes. Existing runtime
health metrics remain available for wider CPU inspection.

The trace preserves its existing 120-event cap and also trims oldest events to
fit below the export size limit during reconnect storms. Old version-2 trace
files remain readable. Diagnostic export includes the new fields without raw
frames, credentials or account identifiers. An observer lock collision does
not create a false disconnect or interfere with the stream.

## Cumulative 1.6.3 changes

This installer also includes the earlier display fixes: a single fresh quote
drives both the forming candle and current-price badge; historical chart views
hide the live badge and offer `현재 봉으로`; the selected chart has a lazy,
display-only ticker connection with idle cleanup. Ranking display snapshots
avoid collecting data under the display lock. Duplicate full candle events
are removed. Diagnostic/update regions have fixed heights and persistent
buttons. Compact positions and one-line strategy rows are retained.

## Validation

```sh
PYTHONDONTWRITEBYTECODE=1 python android/phone_v164_tests/run_validation.py
PYTHONDONTWRITEBYTECODE=1 python android/phone_v164_tests/benchmark_monitor.py
```

Requires Python 3.12, requests, websocket-client, python-dotenv and Node.js.
The replay benchmark also requires OpenSSL. The runner reconstructs 148
hash-verified core files and previous hosts from repository artifacts, builds
the cumulative installer, and records results and log hashes in
`validation.json` and `validation_logs/`.

The recorded full run passed **325 Python tests and four JavaScript suites**.
The additional 16 monitoring tests cover split and extended-length frames,
fragmentation, protocol ping/close, strict UTF-8, partial timeouts, true EOF,
socket replacement, execution isolation, monitor-only recovery traces,
clock/CPU observations and bounded diagnostic export. The full recorded
regression result is in `validation.json`. Inherited tests use actual engine,
strategy, fill reconciliation and stop-verification functions with fake
exchange I/O, including position-preserving upgrade and rollback.

The local benchmark replays 60,000 ticker messages across 290 symbols through
verified in-memory TLS, the unchanged WebSocket parser and the production
fast ticker feed. It compares the exact 1.6.3 transport against 1.6.4 in three
alternating pairs. All message, latest-quote and intrabar-band hashes matched.
The recorded burst replay reduced median CPU time from 1.695390 to 1.310814
seconds (22.68%); TLS reads fell from 181,143 to 1,154. This is a buffered local
burst workload, not measured Android CPU savings or real-network latency.
Exact samples and environment versions are in `monitor_benchmark.json`.

No actual exchange order was sent. UI checks use a simulated DOM, not the
user's phone browser. Actual phone uptime, network recovery, live fills and
profitability are not established by these offline tests.

## Release scope

Entry patterns, time windows, sizes, the shared-three plus reserved-one
allocation, order/SL/exit management, credentials and the 148 pinned core
files are unchanged. Prior installers remain immutable. This is
host-v51/service-51, cumulatively upgradeable from hosts 24–50 through the
existing position-preserving handover and verified previous-host restoration.
