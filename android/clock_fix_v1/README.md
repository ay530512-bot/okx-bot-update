# Phone shared-clock fix v1 — 2026-11-13

This fixes redundant public server-time requests in the Android Q2X host. It is
not a strategy release and does not change the original 148-file Q2X tree.
The standalone installer is `android/phone_clock_fix.py`; this directory is
its reproducible source. The existing watch-only home installer stays unchanged.

## Observed incident and scope

The operator's 2026-11-13 10:31:05 KST diagnostic reported three HTTP 429 replies
to the public time endpoint, two OKX 50011 log matches, a prior private WS
snapshot delay/closed connection and a BrokenPipeError. Host/remote restart
counts were both zero during the sample. The diagnostic scheduler measurement
belongs to the diagnostic process, not the trading engine. Fast 429 replies do
not establish successful exchange data delivery.

Q2X `okx_band_flow.scan` creates 24 disposable worker-local API clients. Each
client's first `now_ms()` calls `sync()` even before the completed-candle cache
check. Original `sync()` does a separate public time GET without a shared gate.
OKX documents `/api/v5/public/time` at 10 requests per 2 seconds, per IP:
https://app.okx.com/docs-v5/en/#public-data-rest-api-get-system-time
(checked 2026-11-13).

This is a reproduced over-requesting defect and a plausible contributor to this
incident. The endpoint-specific distribution of the live engine's 50011 errors
was not recorded, and other clients on the same IP may contribute. It does not
prove every WS/BrokenPipe error or future delay has this cause.

## Change

After source/configuration verification and before API construction, the phone
wrapper replaces only `OKX.sync` with a process-wide, single-flight time reader.
New worker clients borrow a sample younger than 60 seconds, keeping its original
monotonic anchor and observation age. The original existing-client 300-second
private-request refresh rule remains in the verified original code. No local
wall-clock fallback is introduced. On failure, one shared exponential cooldown
(2/4/8/16/30 seconds) prevents waiting workers from hammering the same endpoint.
Expired samples are not served to a failed sync. Existing client fields are not
overwritten when refresh fails.

No entry thresholds, candle worker count, confirmed-candle criteria, capital,
SL, trailing exits, protection reconciliation or freshness blocks are changed.
No write/order retry is added. Time sharing is within one process only.

## Safe installation

Use after the existing phone handover, with **new entries paused** and **all
positions, normal orders and conditional orders absent**. The installer verifies
the exact old host-v4 bundle, original Q2X/configuration pins, account identity,
paused journal and two fresh read-only flat-account snapshots. It stages an
immutable host-v5, gracefully stops the old supervisor, verifies process/socket
release, and checks the account again before starting host-v5. It never uses
SIGKILL or starts a second host if shutdown is unconfirmed. A rejected graceful
stop leaves original protection running and requires checking the state.

Owner, credentials, configuration, journals, Tailscale login state and socket
path are preserved. The existing managed boot hook is updated only after stop.
If readiness fails, a guarded rollback restores the old boot hook and launches
the original host with the paused entry intent. If safe rollback cannot be
confirmed, it stops attempting and prints a state-check message. No auto-entry
authorization is written. After success the operator checks the visible
`시각 조회 공유 v1` banner and uses the existing start/confirm controls.

## Validation

Run from this directory (dependencies: original Q2X Python dependencies):

```
python -B test_phone_clock.py --core /path/to/verified-q2x -v
python -B test_clock_upgrade.py -v
python -B build_clock_fix.py
```

Offline tests use mock HTTP and processes, no exchange credentials or orders.
The actual pinned core sends 24 public time GETs for 24 new clients before the
patch and one after it. Concurrent batches, cache expiry, preserved clock age,
429 cooldown, invalid data and non-mutation on failed refresh are checked.
Updater tests cover pause/flat guards, unavailable account reads, duplicate
invocation, successful sequence, refused stop, rollback and immutable staging.
The bundle is deterministic. `validation.json` records results and source hashes.

Android kernel behavior, real graceful shutdown, live order management,
Tailscale continuity, rate-limit recovery on the actual phone, screen-off/Wi-Fi
and long-duration behavior remain **not tested by these offline tests**.
The user must verify actual post-install operation; do not claim the live phone
is repaired merely because these tests pass.
