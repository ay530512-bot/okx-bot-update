# Phone recurrence check v2 — 2026-11-13

The operator confirmed the shared-clock v1 banner and then reported recurrence.
The screenshot shows 11:12:55 KST recovery entry, 11:12:58 public WS connected /
account WS reception confirmed, and dashboard age 22 seconds at 11:13.
It does not show a current 429/50011 error, the actual WS receive age, the last
transport exception or a completed recovery. The clock fix alone has not
demonstrated full resolution of the symptom.

Original `RuleEngine.tick` enters recovery if either WS health fails or the
connection generation tuple changes. Thus restored connections can coexist
with a recovery label while REST account/order/protection checks complete.
Dashboard age measures the wrapper's last dashboard event, not private WS age.
Do not weaken freshness/protection conditions to hide the warning.

The v1 diagnostic public probe used `www.okx.com`, whereas the actual Q2X REST
transport uses `openapi.okx.com`. Its three HTTP429 observations were real for
that probe host, but did not prove that the engine's server-time endpoint was
also being rate limited. The engine separately logged OKX50011. Its precise
endpoint was not shown in the submitted v1 report. The reproduced redundant
time-query defect remains valid; attributing all the live failures to it would
be unsupported.

V2 changes diagnostics only: one unsigned IPv4 time GET to the actual REST host,
the known service version, on-disk clock module hash match, and sanitized logs
for the last 30 minutes filtered after a completed clock installation when that
record is available. Explicitly logged endpoint paths are allowlisted; paths
are not inferred from generic errors. Counts are log matches, not unique
connection failures. No credentials are loaded, no signed reads/orders are
sent, no process signals are sent, and no configuration/state files are written.

Offline tests cover time filtering, redaction, fixed-host GET, symlink rejection,
service allowlists and a single-probe no-file-write run. Live network, Android
and the user's running trading engine are not accessed by these tests.

Official references checked 2026-11-13:
- https://www.okx.com/docs-v5/en/#overview-websocket-connect
- https://www.okx.com/docs-v5/en/#trading-account-websocket-account-channel
- https://www.okx.com/en-us/help/api-faq

Next evidence: the user's post-install v2 output. A warning screenshot alone
cannot distinguish fresh REST limits, WS reconnection, account data delays,
device suspension or slow serialized reconciliation. No second trading patch
or safety-threshold adjustment is made on that evidence alone.
