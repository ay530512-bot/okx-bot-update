# Phone 1.6.11 home asset basis

The displayed daily PnL percentage divides the displayed daily PnL by the latest OKX whole-account USDT valuation. The daily target equals 6% of that same valuation. Remaining target and reached status use the existing net PnL. Both use the same valuation response as the whole-account card. Missing or non-positive valuation leaves the calculations unavailable. A retained stale valuation is labeled on the home screen.

This projection applies to dashboard snapshots only. It does not use the previous available-balance journal fields. Trading rules, sizing and protection continue to use their existing inputs.

Run `PYTHONDONTWRITEBYTECODE=1 python android/phone_v1611_tests/run_validation.py` in the repository root. Tests use a simulated exchange and DOM. Supported predecessor hosts are 24–57.
