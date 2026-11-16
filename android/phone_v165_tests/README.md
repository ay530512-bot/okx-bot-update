# Phone 1.6.5 — readable diagnostics and compact direction analysis

Each diagnostic snapshot previously removed every text node and rebuilt the
scrolling region. A temporarily unavailable report also replaced the reading
content with a collection placeholder. This release reconciles sections and
rows in place. Unchanged text is untouched, signal records keep stable keys,
and both outer and nested scroll positions retain their visible anchor.

The last received diagnostic content stays visible when a report is missing.
A persistent label explicitly identifies it as the last confirmed data;
the entry summary does not label the missing report as current permission.
An unknown monitoring connection value is displayed as waiting for confirmation,
not as a confirmed disconnection.

The small **읽기 고정** button freezes only the displayed diagnostic content.
**최신 보기** resumes with the latest received snapshot. Background data receipt,
bot execution and diagnostic-file export are unchanged. The save button retains
its identity, pending state and handler across all updates.

## Direction analysis

The analysis panel has smaller typography and four compact parts: analysis
basis, confirmed-candle indicators, a long/short SL and partial-exit comparison,
and expandable cost/remaining-position notes. Scores appear once. The visible
caption states that these are indicator scores, not win or profit probabilities.

The UI reads the existing numeric analysis fields rather than parsing the long
description string. It retains the existing 5x example, 2ATR SL, +20% ROE half
exit, costs and net-per-margin values. If target margin is unavailable, amounts
are explicitly shown per 1 USDT of margin. These are conditional examples,
not calculated expected returns or promises of final PnL.

Existing analysis freshness and symbol checks remain in force. If data becomes
stale, current score headers show dashes and retained same-symbol details are
marked as the last analysis. Changing symbol removes the previous symbol's
figures. Expanded notes and unchanged table nodes survive refreshes.

## Validation

```sh
PYTHONDONTWRITEBYTECODE=1 python android/phone_v165_tests/run_validation.py
```

The runner reconstructs the 148 pinned core files and historical hosts from
repository artifacts, builds the cumulative installer, and records exact results
and log hashes in `validation.json` and `validation_logs/`.

The final recorded run passed **325 Python tests and four JavaScript suites**.

The UI regression exercises repeated snapshots, changing reason counts, missing
reports, freeze/resume, nested signal identity, unchanged text writes, persistent
save state, conditional PnL formatting, analysis expiry, symbol changes, unknown
margin and expanded-note retention. It uses a minimal DOM that models parent
links and node movement. It performs no trading control request.

Inherited tests cover engine, strategy, fill reconciliation, stop verification,
streaming transport and position-preserving upgrades with simulated exchange
I/O. The full outcome is in `validation.json`. No actual phone browser, exchange
fill or sustained phone connection is verified by this offline run.

## Release scope

Host-v52 / service-52 / display 1.6.5, upgradeable from hosts 24–51. The release
includes 1.6.4's monitoring-receive improvements and two-line home status.
Trading rules, prices used by the engine, order readiness, sizing, SL/TP handling
and the 148 pinned core files are unchanged. Previous installers remain
immutable. The existing handover and rollback mechanism is retained.
