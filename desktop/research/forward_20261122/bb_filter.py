"""Judge a known anchor and a later live retest using fully closed five-minute bars."""
import numpy as np
import pandas as pd

def close_bands(five):
    close = pd.Series(five[:, 3])
    return close.rolling(20).mean().to_numpy(), close.rolling(20).std(ddof=0).to_numpy()

def preceding_decline_and_pause(five, mean, std, anchor, retest_bar, side, atr):
    if anchor < 24 or retest_bar <= anchor or not atr > 0:
        return 0, False, False
    indices = np.arange(anchor - 5, anchor + 1)
    extreme = five[indices, 2] if side == 1 else -five[indices, 1]
    outside = np.flatnonzero(extreme < side * mean[indices] - 2 * std[indices])
    approach = (len(outside) >= 3 and extreme[outside[-1]] < extreme[outside[0]]
                and side * (five[anchor, 3] - five[anchor-6, 3]) <= -atr
                and side * (mean[anchor] - mean[anchor-5]) < 0)
    bars = five[anchor+1:retest_bar]
    pause = (2 <= len(bars) <= 5 and bars[:,1].max() - bars[:,2].min() <= 1.5 * atr
             and abs(bars[-1,3] - bars[0,0]) <= .5 * atr
             and (bars[:,2].min() > five[anchor,2] if side == 1 else bars[:,1].max() < five[anchor,1]))
    return len(outside), bool(approach), bool(pause)
