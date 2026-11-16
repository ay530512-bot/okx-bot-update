# Phone 1.5.4 validation

Run from a disposable checkout with Python 3.12, requests, websocket-client,
python-dotenv and Node.js:

```sh
PYTHONDONTWRITEBYTECODE=1 python android/phone_v154_tests/run_validation.py
```

The runner reconstructs 148 hash-checked core files and four older host
references, then builds the cumulative immutable installer. All account,
order, fill and protection responses are simulated. No live credentials or
exchange write requests are used.

`test_position_handover.py` uses records created by the actual RuleEngine
for all eight rule/direction paths. It reproduces the old `KeyError: avg_px`
and verifies reconciliation of the real `market_fill_stats.avg_px` / `fill_px`
fields, position identity, protection, and preserved journal data. It also
exercises the real pause/rejected-quit semantics: quit with owned positions
DOES NOT persist a quit event. Display evidence is passed through the mobile
field allowlist; unknown records are not assigned a guessed entry reason.

`test_legacy_restart.py` uses disposable real Linux processes and file locks.
It checks protected-position replacement, user-pause precedence, absent or
changed stops, PID token mismatch, pre-commit installer death/lease expiry,
and post-commit retirement/recovery. The remote daemon is absent in this
fixture; its socket-release probe is mocked because AF_UNIX is forbidden by
the runner. Android process permissions and the actual Tailscale daemon have
not been exercised.

Ordinary future updates retain cooperative engine handover. The one-time
legacy path pauses entries, freezes the identified old writer and supervisor,
compares journal plus read-only REST position/SL facts twice, then retires
that frozen legacy process. The exchange SL remains registered; local
trailing/profit checks pause until the replacement has reconciled. Unknown
orders, unstable ownership/protection or an incomplete write intent defer it.
No stop, order, position, sizing, leverage or strategy predicate is changed by
this updater. A separate watcher thaws a pre-commit failure, or restarts the
prior owner after committed installer death and released owner locks.

Two JavaScript DOM suites verify field placement, expansion/scroll retention,
unknown-record wording, existing close-action keys and disabled/stale gates.
These are DOM/stylesheet checks, not rendered mobile/device tests. A full
Playwright test is included (`prepare_ui.py`, `test_browser.cjs`) but could NOT
run in this environment: browser launch requires a prohibited AF_UNIX socket;
the browser service also prohibits local file navigation. Do not report pixel,
Safari, touch-device or live-phone validation from these results.

The previous CPU/transport/entry fixes are included byte-for-byte. Their prior
load evidence lives under `phone_v152_tests` and `phone_v153_tests`; it is not
new Fold3 performance evidence. This release does not establish actual phone
installation, uninterrupted live connections, live fills or profitability.
