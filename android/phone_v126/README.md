# Phone 1.2.6: reversible four-process calculation trial

Adds four spawned workers for pure signal packet calculation. The parent retains candidate filtering, signal identity/expiry, priority, latest quote checks, final admission, sizing, journal, order submission and all protection. No strategy/core edits. This is a device trial, not a guaranteed speed or connection fix.

## Use / rollback

- Upgrade from 1.2.5 (host-v23) only, using the existing safe handover. The installer does not force a takeover when protection/pending execution is uncertain.
- Initial preference defaults to four workers. Activity/settings shows `4개 분산 사용` and `기존 방식으로 복원`.
- Restore selects the 1.2.5 serial calculation path at the next candidate check, shuts down worker processes, and persists across restarts. App version stays 1.2.6; this is a calculation-mode restore, not a whole-binary downgrade.
- Switching modes does not close positions, cancel protective orders, change entry permission, or change rules. Selecting four workers again is also supported.
- Worker startup, crash, timeout, invalid response or preference failure skips that candidate pass and falls back to serial. Startup and a worker batch each have an eight-second deadline; no unbounded IPC wait in the trading thread. Next pass can use serial. A calculation preference read failure also falls back.
- A preference change or connection-generation/freshness change during calculation discards the batch. Current inputs/config/15-minute cutoff are compared again for each parent lookup; changed inputs use the existing serial path. Existing final live checks are retained.
- Worker aggregate CPU/RSS are shown in addition to the parent-only resource display; 100% remains one-core-equivalent units. RSS sum can count shared pages more than once.

Emergency calculation restore in Termux (does not restart the trading engine):

```bash
python -B ~/okx-phone/host-v24/phone_parallel.py serial
```

Re-enable four workers:

```bash
python -B ~/okx-phone/host-v24/phone_parallel.py parallel4
```

## Validation

100 offline Python tests and 7 DOM UI checks passed. Tests include real spawned workers; signal/priority equality; expiry during calculation; historical corrections; real quote-reader rejection of stale/future/prior-generation quotes; held/manual/seen filtering; failed workers; deadlines; manual restore and restart persistence; connection change during a batch; authenticated loopback HTTP controls and Origin rejection; idempotent mode requests; predecessor updater compatibility; existing handover/rollback fault cases.

No actual Fold measurement, exchange connection endurance, real fills or actual protective-order placement is claimed. Existing WebSocket transport is byte-identical. This update does not claim to eliminate EOF disconnections.

## Actual integrated benchmark (final code)

12 isolated cases, 168 scans, same 289-symbol retained/synthetic inputs; all per-scenario candidate hashes match. x86 server, Python 3.12; not phone latency. Three repetitions per mode/workload. Cold includes worker startup. Median elapsed time includes current-input validation, IPC and parent candidate processing.

| Synthetic workload | Mode | Cold ms | Warm ms | All changed ms |
|---|---|---:|---:|---:|
| mostly_waiting | 0 workers (0=serial) | 424.73 | 6.78 | 442.88 |
| mostly_waiting | 4 workers (0=serial) | 480.69 | 8.15 | 340.69 |
| many_signals | 0 workers (0=serial) | 542.75 | 40.67 | 557.88 |
| many_signals | 4 workers (0=serial) | 459.44 | 23.73 | 340.18 |

**Negative result retained:** mostly-waiting warm scans were approximately 20% slower (6.78→8.15ms), and cold startup was slower. Four workers improved full recalculation by approximately 23–39%, and many-signal warm scans by approximately 42%. The earlier research prototype’s 61% improvement must not be advertised as the integrated release gain. Phone performance remains to be measured.

A preliminary pre-connection-guard integration run measured mostly-waiting warm 6.874→7.208ms (~5% slower), full-change 436.402→324.478ms; many-signal warm 41.788→22.483ms, full-change 573.460→366.689ms. After adding the connection-generation guard the required benchmark was rerun, with the final complete raw records preserved in benchmark.json. The preliminary complete raw file was overwritten; only its console summary was retained. No positive-only selection is used.

## Reproduce

Use the pinned core and host-v23 from the preceding multicore research checkout. `build_release.py` stages host-v24 only; it does not start a service. Install websocket-client 1.8.0, run `run_validation.py`, and run `benchmark_release.py`. Paths are sibling core121 / fixture121. The validation runner also expects websocket-client in /tmp/okx123deps for this environment.

Files: standalone incremental installer is `../phone_1_2_6_setup.py`; source/hashes/test outputs are in this directory. No API keys or account state are included.
