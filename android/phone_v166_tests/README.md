# Phone 1.6.6 — compact funding and nearby manual controls

Funding is now two stable lines inside the direction-analysis card: the next one-time rate/settlement time, and the estimated long/short receipt or payment at the existing manual 5x target margin. The separate large funding card is removed.

The original long/short buttons and their existing status elements are moved intact above the detailed indicator/SL/TP tables. IDs, disabled gates and handlers are unchanged. Settlement expiry, quote age, symbol mismatch and unknown margin suppress estimated cash amounts. Positive, negative and zero funding retain their correct pay/receive direction. Unchanged text nodes remain intact on refresh.

## Validation

Run `PYTHONDONTWRITEBYTECODE=1 python android/phone_v166_tests/run_validation.py`.
Exact outcomes and hashes are in `validation.json` and `validation_logs/`. Tests cover the final assembled asset, original control identity/gates, funding signs/expiry, stable DOM updates, and inherited strategy/execution/upgrade regressions using simulated exchange I/O. No actual phone browser, real fill or sustained phone connection is verified.

## Release scope

Host-v53 / service-53 / display 1.6.6, upgradeable from hosts 24–52. All previous fixes remain included. The 148 pinned core files, live strategy rules, entry hours, sizing and SL/TP management are unchanged. Strategy research is separate and is not installed by this update. Previous installers remain immutable; the existing position-preserving handover and rollback mechanism is retained.
