# 1.2.2: remove expensive completed-candle cache

Phone telemetry on 2026-11-15 identified 365157 completed-candle cache reuses consuming 5621.507 seconds of inclusive wall time at that leaf, versus 8371 original validations consuming 117.065 seconds. These are unequal live workloads, not a controlled benchmark or pure CPU measurements.

Remove only completed-candle memoization, its serialization, alignment pre-pass, and deep-copy of full bar arrays. Run the original validation on every call with exact current time. Keep candidate-only auxiliary-analysis early return and exact-input pattern caching from 1.2.1. Strategy, sizing, final admission, stops, order checks, and position handover remain unchanged. This is a measured bottleneck correction, not a guarantee of entries or zero WebSocket disconnections.

Installer pins exact host-v19 sources and stages host-v20. Existing serial handover compares positions, orders and protection, defers or rolls back when unsafe, and preserves prior run intent. No direct exchange requests in the installer.

Validation:
- Exact pinned Q2X core: 81 fixtures (one positive fixture plus 80 synthetic), 8 scans including repeated inputs, expiry and historical corrections: identical pending-signal results to original core.
- Full packet quote refresh and final admission bypass checks passed.
- 22 offline handover/transaction tests passed.
- Installer stage/idempotence and unchanged strategy/sizing/handover/transport source bytes checked.
- No live phone or account test; actual phone latency after installation remains to be measured.

Reproduction (from repository root, with exact core/host directories supplied):
```
OKX_TEST_CORE=/path/to/pinned/core OKX_TEST_HOST=/path/to/host-v20 python android/phone_v122/test_candidate_fast.py
PYTHONPATH=/path/to/host-v20:android/phone_v118 python -m unittest test_handover test_update_transaction
```
