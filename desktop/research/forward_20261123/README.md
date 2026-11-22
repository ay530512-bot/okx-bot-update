# 2026-11-23 KST internal research ledger

This directory is separate from the installer and the active runtime. No private PC journal, credentials or orders are used. The package digest and reference are in protocol.md. The retired 13-rule schedule has no admission or observation route in this study.

## Cohorts

* The PC 2.16.0 public release is the production code reference. The selected user mode, real fills, live order book, trade receipt latency, and local PC 2.15 simulated observations are not observed. Last-trade/mark reproductions and economic scenarios are modeled.
* The archived 60-event diagnosis and prior experiments remain development comparators. historical_60.json contains the original 8/52 split, before-entry group statistics, independently replayed opposite outcomes and matched-size exit comparisons. It is not a new sample.
* The just-completed 11-22 session was already opened and partly studied before registration. Its entire date is exploratory. 11-23 had begun and not closed at run time. Do not append either date to this new protocol's 60-day evidence. Earlier fully specified 11-22 protocols retain their own original 11-23 forward start.
* The dated run record identifies coverage, incomplete paths, assumptions and any account totals. A matching opportunity, a forward price change and a simulated fill are different columns. Native pace uses exact turnover; the product's proxy remains identifiable.
* No change to the existing trading/alert channel follows from this comparison. A user-requested action or result is separate from the silent research job.

## Reproduction

Unpack the release ZIP fixed in protocol.md. The package argument is its OKX_PC_PACKAGE directory. Python 3.11+ and matplotlib are needed, plus network access to the OKX public history endpoints for uncached data. The included 31-contract cache has verified confirmed original candles, actual funding observations, mark candles and contract specifications. Contract specifications are the snapshot queried at collection time. Funding settlement is charged only when exposure straddles it. Source-day archive availability is a check at the recorded run, not a permanent archive guarantee.

    mkdir -p session/cache
    cp 20261122/cache/* session/cache/
    python pack_inputs.py restore 20261122/tape session/ticks
    python replay_day.py 2026-11-22 session /path/to/OKX_PC_PACKAGE
    python check.py session/cache

Each date gets its own directory. Once forward evaluation starts, pass the immediately preceding date's result/daily_state.json using --previous. A missing prior balance results in an unverified account day, not a reset to 150. Initialize only at the registered first date for this experiment. Retain previously consumed anchor states and resolve ambiguous cross-midnight setups before treating a continuous forward account as complete. Unknown cross-midnight eligibility is flagged in this version. Missing-print and ambiguous exit rows need independently auditable repair before any promotion. The daily +7.5% account-lock comparator samples net liquidation on completed minute marks and requires a strictly later tradable print to flatten; it does not clamp the closing NAV. Drawdown fields specify the valuation sampling resolution.

The historical desktop/research/{daily_close_20261122,compound_band_20261122,wick30_scalp20_20261122,pc290} directories retain their individual controls with their original specifications. All experiments in this directory are research-only. Do not silently merge or treat the new 5m local-pivot study as the 15m Bollinger two-wick strategy or the 5m scalp-long rule.
