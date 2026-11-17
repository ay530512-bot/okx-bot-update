# Phone 1.6.7 — continue management after manual partial closes

Every currently enabled automatic rule can reconcile a manual reduction of its own position: pullback long/short, reversal long/short, double-wick long/short, live leader long and morning leader short. The journal retains the original entry, rule, observed peak, timing and tighter protection targets. Remaining quantity and committed margin are reconciled from account data and a complete replay of the entry/exit fills. Repeated reductions and restart recovery use the same path.

The remaining quantity receives a replacement protective stop. Its request intent is saved before submission; unknown responses are queried instead of retried. Existing stops are removed only after the replacement is independently verified. A protective rejection or crossed protection level uses the existing close path for the actual remainder. A user/risk full-close request does not stall behind an already confirmed reduction.

A manual partial close suppresses another automatic first-half order, but does not fabricate an automatic profit-target observation or a realized PnL. Existing profit latches, tighter stops and trailing remain effective. A full manual close retains the existing two-observation flat confirmation. A delayed fill lookup holds the affected slot and new entries while other confirmed positions continue their management loop.

The updater can perform a read-only, protected handover from the previous version's quantity-mismatch state when the complete fill proof and exchange stop coverage match. The installer never rewrites position quantities or sends exchange orders. Existing process freezing, double validation and rollback remain in use. Increased quantity, a changed identity, foreign opening fills, a fully closed/reopened position or incomplete evidence are not silently adopted. `posId` alone is insufficient evidence because it can be reused.

## Validation

Run `PYTHONDONTWRITEBYTECODE=1 python android/phone_v167_tests/run_validation.py`.
Exact outcomes and hashes are in `validation.json` and `validation_logs/`. New tests cover all eight entry paths, repeated reductions, four concurrent slots, missing/duplicate fills, protection ACK loss/rejection, full-close races, restart, paused-entry management and the process handover. Inherited strategy/execution/transport/UI/upgrade regressions also run. Exchanges are simulated and network access is blocked in the execution harness. No actual phone browser, real fill or sustained phone connection is verified.

## Release scope

Host-v54 / service-54 / display 1.6.7, upgradeable from hosts 24–53. All previous fixes remain included. The 148 pinned core source files remain unchanged; the new host adapter wraps quantity/protection reconciliation in memory. Entry rules, hours and sizing are unchanged. No research strategy is installed. Previous installers remain immutable.
