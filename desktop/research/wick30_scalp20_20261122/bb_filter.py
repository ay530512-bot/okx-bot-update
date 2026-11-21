"""The Bollinger reversal gate for an observed second-wick trigger."""
import math

import numpy as np
import pandas as pd

MAX_RETEST_BARS = 30


def within_retest_window(anchor, retest_bar):
    """The next 5-minute bar is 1. The signal is valid through the last tick of bar 30."""
    return 1 <= retest_bar - anchor <= MAX_RETEST_BARS


def close_bands(five):
    close = pd.Series(five[:, 3])
    return close.rolling(20).mean().to_numpy(), close.rolling(20).std(ddof=0).to_numpy()


def preceding_decline_and_pause(five, mean, std, anchor, retest_bar, side, atr, *, observed_prices=None):
    """Check a separately detected retest. For adjacent candles pass prices only through its triggering trade."""
    if anchor < 24 or not within_retest_window(anchor, retest_bar) or not math.isfinite(atr) or atr <= 0:
        return 0, False, False
    indices = np.arange(anchor - 5, anchor + 1)
    extreme = five[indices, 2] if side == 1 else -five[indices, 1]
    outside = np.flatnonzero(extreme < side * mean[indices] - 2 * std[indices])
    approach = (len(outside) >= 3 and extreme[outside[-1]] < extreme[outside[0]]
                and side * (five[anchor, 3] - five[anchor-6, 3]) <= -atr
                and side * (mean[anchor] - mean[anchor-5]) < 0)
    if not approach:
        return len(outside), False, False

    between = five[anchor+1:retest_bar]
    if len(between):
        low, high = between[:, 2].min(), between[:, 1].max()
        opening, last = between[0, 0], between[-1, 3]
    else:
        if observed_prices is None:
            raise ValueError('The adjacent retest requires the observed trade prefix through the trigger.')
        if len(observed_prices) < 2:
            return len(outside), True, False
        prices = np.asarray(observed_prices, dtype=float)
        low, high = prices.min(), prices.max()
        opening, last = prices[0], prices[-1]
    holds = low > five[anchor, 2] if side == 1 else high < five[anchor, 1]
    pause = high - low <= 1.5 * atr and abs(last - opening) <= .5 * atr and holds
    return len(outside), True, bool(pause)
