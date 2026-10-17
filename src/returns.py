import numpy as np


def compute(day, night, prev, open_, close):
    if not np.isfinite([day,night,prev,open_,close]).all() or min(day,night,prev,open_,close) <= 0:
        raise ValueError('Invalid price')
    gap, intraday, total = open_/prev-1, close/open_-1, close/prev-1
    if not np.isclose(1+total, (1+gap)*(1+intraday), atol=1e-12):
        raise ValueError('Return decomposition failed')
    return dict(txf_overnight_return=night/day-1, spot_opening_gap=gap,
                spot_intraday_return=intraday, spot_total_return=total)
