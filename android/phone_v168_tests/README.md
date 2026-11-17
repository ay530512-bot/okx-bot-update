# Phone 1.6.8 — unblock updates when paused and flat

The installed 1.6.6 handover rejects queued commands, queued risks, the risk-ID set, a pending approval and manual-entry work with one generic message before its account reads. An orphan risk ID therefore blocks handover even with no journal position and an empty exchange account. The screenshot does not identify which of those fields was set on the actual phone. The old-runtime reproduction demonstrates the failure without inferring a live holding from that message.

The cumulative installer retries a known busy handover once. Only that bound busy response can select the new fallback. It requires an explicit persisted entry pause, no local owned/submitted/closing/manual-close records, and two independent empty exchange observations covering positions, normal orders and all conditional orders. It then signals the verified original host for its normal serial pause/quit, waits for every original owner and transport to release, and checks the paused journal and exchange again. It never clears risk flags, deletes the journal, cancels orders, sends trading requests or escalates to a forced exit. The new service retains the paused entry intent.

A real owned position makes the existing engine refuse quit and continue protection. A failed post-stop check restores the original service. A separate recovery watcher can restore it after installer death, but only after all owner locks/processes/transport are released; it does not replace an already running replacement. New handover diagnostics identify the waiting component and count instead of implying that a risk flag proves a held position.

All 1.6.7 manual partial-close management changes and prior entry/ranking/UI fixes remain included. The existing protected-position handover paths are unchanged. This fix does not claim that the phone's live account has been inspected from the development environment.

## Validation

Run `PYTHONDONTWRITEBYTECODE=1 python android/phone_v168_tests/run_validation.py`.
Exact counts, outcomes and artifact hashes are in `validation.json` and `validation_logs/`.

New tests reproduce the old 1.6.6 busy rejection, exercise its actual request/ACK files and PID identity with disposable Linux processes, and verify normal exit, original pause retention, transient retries, exchange/order/journal blockers, a changed process identity, query failures, restoration after exit and installer-death recovery. A separate test invokes the real serial trading engine: a stale risk flag allows its ordinary flat quit, while a held position refuses quit and keeps its protection. Tests use GET-only fake exchange observations; the real-engine harness blocks network access. The transport socket is stubbed in process tests because AF_UNIX is unavailable in this runner.

Inherited tests cover all eight automatic entry paths, four slots, repeated manual reductions, protected restart/handover, execution and UI. No actual phone installation, real exchange fill or sustained phone connection has been verified.

## Release scope

Host-v55 / service-55 / display 1.6.8, upgradeable from hosts 24–54. The 148 pinned core files and all strategy predicates, hours, sizing, ranking and manual-reduction logic remain unchanged. Previous installers remain immutable.
