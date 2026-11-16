# Phone 1.5.0 offline validation

Run `python android/phone_v150_tests/run_validation.py` from a disposable checkout.
Python 3.12, Node.js, python-dotenv and websocket-client are required. No real
exchange credentials are required or used. The execution harness blocks network
connections; the authenticated export test uses only a local HTTP server.

`prepare_tests.py` restores 148 exact-hash core files and the historical candle
fixtures from artifacts already in this repository. Fixtures are deliberately
not duplicated here. Prior host sources are extracted for regression comparison.
References are written to sibling `core121/` and `regression_hosts/` directories;
different existing files are never overwritten.

`build_release.py` deterministically packages the 41 runtime files into the
cumulative installer and records hashes in `release.json`. `validation.json`
and `validation_logs/` record the shipped checks. There are 173 Python tests and
one JavaScript suite. `results.json` contains the 38 baseline execution checks,
including original trend LONG and six common direction-specific routes.

Morning pattern, trailing, and reversal tests use synthetic candles. Baseline
entry tests reuse historical candles from the 1.4.2 audit; quotes, account,
contract metadata, fills and protection acknowledgments are simulated. Passing
these checks does not establish actual-device operation, actual exchange fills
or profitability. See `../phone_1_5_0_notes.md` for user-visible behavior.
