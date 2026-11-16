# Phone 1.5.3 validation

Run from a disposable checkout with Python 3.12, websocket-client, requests,
python-dotenv, Node.js and (for the TLS test) OpenSSL:

```
PYTHONDONTWRITEBYTECODE=1 python android/phone_v153_tests/run_validation.py
PYTHONDONTWRITEBYTECODE=1 python android/phone_v153_tests/audit_loaded_entry.py
```

The first command restores 148 hash-checked core files to sibling `core121/`
and four reference hosts from existing repository archives, builds the
cumulative installer and runs 231 Python cases plus one JavaScript suite.
The execution harness blocks external networking. Accounts, quotes, order
acknowledgments, fills and protective orders are simulated.

`test_listing_baseline.py` reproduces the 1.5.2 global ranking wait caused by
a newly listed SWAP without a KST09 reference. It requires verified instrument
type, identity, state and listing timestamp before excluding that instrument
from this ranking only. Existing-symbol missing data and unknown/invalid/future
listing metadata still block ranking. Exact-reference-time listings remain
eligible, and excluded listings rejoin after the next reference date. Both
reserved strategies go through full engine ticks to a single simulated order,
fill and verified SL with a new listing present. No strategy pattern,
quantity, leverage, freshness, 90-second expiry or protective rule is relaxed.

`listing_evidence.json` records the public JCT instrument metadata obtained
from OKX. Its 2026-11-16 11:00 UTC listing is after that day's 00:00 UTC
(KST09) reference, matching the user's three-hour candle history. The official
announcement is linked in that record. No personal account data is included.

`audit_loaded_entry.py` tests all eight rule/direction combinations with a
290-symbol universe, four real calculation processes and concurrent local
TLS/WebSocket readers. It withholds trades for ten seconds and injects two
monitor EOFs and one execution EOF per case before admitting the single order.
The new listing is also present; both reserved-strategy cases require its
baseline exclusion. `loaded_entry_results.json` records per-case outcomes and
exact runtime hashes. This test uses synthetic market/account data and local
TLS with certificate and hostname verification; it does not contact OKX.

The transport, feed, coordinator, computation, account, protection, handover
and CSS files are byte-identical to 1.5.2. The direct installer tests cover
both 1.5.1 and 1.5.2. The 1.5.2 transport audit and synthetic performance
measurements remain in `../phone_v152_tests/`; they are not phone benchmarks.
No test result establishes actual Fold3 latency, live fills, profitability,
or an uninterrupted four-hour connection to OKX.
