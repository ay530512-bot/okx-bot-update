# Phone 1.5.6 compact position layout

This release changes position presentation and release/version registration.
The position renderer, persisted entry evidence, close-button handlers, entry
rules, execution, protection, market data and 1.5.5 recovery module are unchanged.

The previous compact styling left the two-ID `#part-chart #current` margin and
`.mobile-part section` top/bottom padding active. This version overrides the
actual selectors and clears section padding around positions and the chart.
Values are 12px instead of 15px. Metric labels and values share each cell's row,
with three columns normally and two below 360px. Long values can wrap rather
than being clipped. The entry reason remains visible; expanded evidence and
existing financial control gates are preserved.

Run from the repository after preparing the reference files with
`android/phone_v155_tests/prepare_tests.py`:

```sh
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$PWD/android/phone_v156:$PWD/../core121"
python android/phone_v156_tests/build_release.py
python android/phone_v156_tests/test_release.py
python android/phone_v156_tests/test_handover.py
node android/phone_v156_tests/test_positions_ui.cjs
node android/phone_v156_tests/test_ui.cjs
```

The 19 Python tests cover release staging/pins and existing position handover;
the two JavaScript suites cover DOM data, expansion/scroll retention, exact
close-action keys and disabled/stale gates. They are offline fixtures, not
rendered Safari, physical phone or exchange execution validation. The prior
250-test 1.5.5 report is retained separately; it was not rerun for this CSS change.
