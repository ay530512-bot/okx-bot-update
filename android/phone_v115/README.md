# OKX Ai trade - 1.1.5

Phone-only performance follow-up; trading rules and limits unchanged.

1.1.4 phone measurement: optimized287 ticks total1524.376985s, signal evaluation1014.719233s; three input-key scopes total800.864789s. These are elapsed times including possible thread scheduling, not pure CPU. Cache hit rate alone was not proof of speed gain. Underlying cause of all elapsed delay remains unproven.

Replace per-call SHA256 with exact serialized input bytes as dictionary keys (hash collisions are checked by full equality). Share input serialization only within one synchronous packet for the same object, retaining references to prevent ID reuse; discard this identity map on return. Every later packet reserializes input values. Historical corrections, new candles and config changes remain observable. Misses compute from serialized snapshots. Returned values are copied. Bounded4096 entries and32MiB serialized key budget (output/object overhead additional). No persisted cache; no API response or time-sensitive verdict cache. Original packet validity, time expiry, quote and final admission checks run. No change to API limits, risk limits or trading cadence.

Performance report version3 adds last40 packet/admission exceptions: static reason category, exception type, source function/line, timestamp. Raw exception messages and credentials never recorded. Exceptions rethrow unchanged; unknown types are unclassified. These events do not prove whether an order was sent or filled. Existing three admission exceptions cannot be retrospectively diagnosed from prior timing counts.

Updater clears an expired/mismatched install ticket so the next click checks the release again. User/session validation is retained. Existing1.1.4 has this bug until updated; a previously stuck ticket may require the verified standalone installer.

26 tests: original signal equivalence including historical positive OP fixture, full input changes, new candle boundary and expiry, final admission bypass, exception propagation/redaction, memory bounds, per-packet sharing, updater ticket recovery and existing install/rollback/security tests. Local synthetic289 warm packets: uncached0.961875s versus cache0.258687s. Not actual Fold speed or profitability evidence; no live orders tested.

Reproduce with pinned Q2X runtime matching phone_sources.json and dependencies:
`OKX_TEST_CORE=/path/to/runtime PYTHONPATH=/path/to/phone_v115 python -m unittest test_signal_cache test_button_upgrade test_phone_mobile_integration test_performance test_followup -q`
`python build_phone_button.py`

Only exact host-v12 supported; account must be paused and flat. No automatic liquidation/order cancellation. User explicitly starts live trading after installation. Report command:
`python -B ~/okx-phone/host-v13/phone_performance.py`

Version policy major/rules/minor. PC distribution unchanged. Actual Fold gain and earlier admission exceptions still require observation/log evidence.
