# OKX Ai trade 1.5.4

- Fix protected-position updater reconciliation: production records store the
  fill average under `market_fill_stats.avg_px` / `fill_px`, not `avg_px`.
- One-time pinned legacy checkpoint restart supports already-open auto
  positions. No exchange order/cancel/amend calls. It preserves the journal,
  quantity, SL and original entry intent. A user stop always wins.
- Exchange protection stays registered during process replacement; local
  trailing/profit management briefly pauses. Missing or changing protection,
  pending writes or unverifiable ownership defer the replacement.
- Compact position card: aligned 3-column figures; persisted entry rule and
  conditions; expandable numerical evidence and KST timestamps. Unknown
  entry reasons remain explicitly unknown. Close-button safety gates remain.
- Bound signal progress history to a scroll panel; retain scroll offset on
  refresh. Future install errors show the specific bounded failure reason.
- Includes 1.5.2 CPU/connection isolation and 1.5.3 new-listing rank repair.

Validation and actual limits: `phone_v154_tests/validation.json` and README.
All orders/fills are simulated. Actual Fold3 installation, continuous OKX
connections and live fill/protection recovery are not verified here.
