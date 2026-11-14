# OKX Ai trade - 1.1.8

Phone updater change: automatically pause new entries, retain owned-position state and broker SL orders, then restore the prior run intent through the existing Q2X reconciliation checks. A previously paused bot stays paused. No entry/exit/risk rules or installed strategy settings change. All 148 pinned original source files remain identical.

## Handover protocol included in this release

The detached installer stages and verifies its files first. The managing engine receives a nonce- and process-bound local request through its serialized command worker. It waits for the current action to finish, inhibits entries, then checks two fresh account/protection snapshots. Unknown positions/orders, changing quantities, incomplete fills, SL replacement, pending close/add operations, missing/duplicate SLs, queued operator commands or protection work defer the handover without terminating the existing manager.

For a successful handover, the engine saves the complete journal without modifying position records (including partial-profit use, original entry time, ownership, strategy and profit protection fields), writes an acknowledgement, and shuts down cleanly. The host lock stays held until the worker exits. The installer waits for old processes, locks and transport to release before starting the replacement. Normal account/order/SL reconciliation gates automatic entry resumption. An operator stop received during handover defeats auto-resume.

Exchange-side SL orders remain live. Local trailing/profit management necessarily pauses during process replacement; this is not zero-downtime trading. No update code places, closes, cancels or amends exchange orders, removes journals, or force-kills a managing process. The normal strategy may still close a position for its own risk/exit reasons before or after handover.

If replacement startup fails, the installer requests a safe handover back before restoring the prior boot hook and manager. If handover cannot be verified, it does not start a second owner. A detached recovery watcher can restart the prior manager after installer death only when old ownership locks/transport are released; it never kills another manager.

## Important one-time 1.1.7 transition

Running host-v13/v14/v15 has no handover command and its mobile install button refuses active entry intent/owned positions. It cannot acquire a new Python protocol merely by copying files. The 1.1.8 bootstrap therefore requires one Termux/SSH launch for this first transition. It automatically sends the existing graceful pause/quit request to the verified old host. If there are owned positions, the old host refuses exit and keeps normal protection/exit management running under its supervisor. The installer waits for natural flatness (up to 24 hours), never forces closure, then installs. Original entry intent is restored only if the continuity history exactly matches the bootstrap's own pause/quit sequence; additional operator stops prevent restoration.

Thus **positions cannot be handed live from an already-running 1.1.7 process**. This release implements the protocol now so installations running 1.1.8 can use the integrated update button with position-preserving handover when a subsequent verified installer supports it. Compatible successor installers must retain this protocol and the new updater path; this is not a promise about arbitrary future packages.

Already stopped installations retain their persisted stop intent. Re-running the installer on a running 1.1.8 is a no-op. Credentials, notifications, source pins, risk/strategy settings and trading journals are never bundled into public releases.

## Validation and limits

Offline tests cover position/partial-state preservation, multiple positions/SL legs, missing/wrong/duplicate SLs, unknown exposure, pending orders/fills, lookup failure, expired/replaced IPC requests, queued and late operator stops, protection events, original paused state, legacy natural-close transition, rollback, recovery locking, and a real local child-process handover. Regression tests retain the 1.1.7 signal-cache, input-invalidation, quote-freshness, transport and authenticated-mobile behavior. Fixture exchange clients expose GETs only.

No real orders were used. Fold3 live-position handover, actual network downtime and Android process survival have not been validated on the user's device. The release preserves strategy semantics; it makes no profitability or latency guarantee.

Reproduce in a Python environment with the pinned original core and requirements_test.txt installed:

```sh
OKX_TEST_CORE=/absolute/path/to/pinned_core python -m unittest discover -s android/phone_v118 -p 'test_*.py' -v
python android/phone_v118/build_phone_button.py
```
