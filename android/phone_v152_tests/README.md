# Phone 1.5.2 validation

From a disposable repository checkout with Python 3.12, websocket-client,
python-dotenv, requests and Node.js installed:

```
PYTHONDONTWRITEBYTECODE=1 python android/phone_v152_tests/run_validation.py
PYTHONDONTWRITEBYTECODE=1 python android/phone_v152_tests/bench_receive.py
PYTHONDONTWRITEBYTECODE=1 python android/phone_v152_tests/soak_transport.py 120
```

The first command restores 148 hash-checked core files to sibling `core121/`,
four old regression hosts and the historical fixtures from existing repository
archives. It builds the cumulative installer and runs the regression suites.
No credentials or exchange orders are used. The execution harness forbids
external socket connections. Prior host sources and user configuration are
not edited. Test-only generated files are ignored as in the predecessor suite.

The soak test requires OpenSSL. It creates a disposable local TLS certificate,
trusts that certificate explicitly while retaining hostname verification, and
redirects only the test's ws.okx.com resolution to its local server. It uses the
production receive/subscription/recovery loop, injects real EOFs on each lane,
and asserts that monitoring failures preserve valid execution observations.
It does not connect to OKX. No certificate or key is committed.

The tests do not claim actual-device latency, fills or profitability. The
benchmark is synthetic and excludes network costs. `validation.json` records
220 Python cases plus one JavaScript suite; `local_soak.json` and
`receive_benchmark.json` record the separate experiments. The transport and
lane suites were also run with websocket-client 1.8.0 (36 cases).

The direct 1.5.1 upgrade test checks every unchanged runtime file byte for byte,
the exact predecessor pin set, installation staging and idempotency. Policy,
account, clock, position protection, handover and CSS files are unchanged.

An additional entry audit exercises eight rule/direction combinations in four
states: first subscription, monitor disconnection, execution reconnection and
cold startup. It starts with no execution quotes for the candidate, sends the
production subscription payload, feeds simulated socket frames through the
production receive/decode/feed functions, and uses full engine ticks for order,
fill and verified protection. All 32 cases preserve the same signal and place
exactly one simulated opening request. Three channels alone and old-generation
quotes cannot place an order. `dynamic_entry_results.json` records the results
and exact runtime hashes. These 32 cases were run after the initial 188-case
validation against the identical published 1.5.2 installer; no runtime change
or additional phone update was made for this audit.
