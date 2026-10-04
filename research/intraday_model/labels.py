"""Training labels use next-open, stop-first outcomes and all modeled costs."""
import math
import numpy as np

try:
    from numba import njit
except ImportError:
    njit = None


def _labels(times, opening, high, low, close, pips, horizon, side_cost,
            minimum_fee, commission_rate):
    n = len(times)
    result = np.full(n,-1,dtype=np.int8)
    stop_distance = pips * .0001
    for signal in range(n-horizon-1):
        entry = signal+1
        if times[entry]-times[signal] > 900:
            continue  # An M15 signal cannot remain executable after a missing-bar/weekend gap.
        mid = opening[entry]
        fill = mid+side_cost
        units = int(math.floor(min(800.0,1000.0-2*minimum_fee,(1000.0-minimum_fee)/(1+commission_rate))/fill))
        if units < 1:
            continue
        entry_fee = max(minimum_fee,units*fill*commission_rate)
        stop,target = mid-stop_distance,mid+stop_distance
        for i in range(entry,entry+horizon+1):
            exit_mid = -1.0
            if opening[i] <= stop or opening[i] >= target:
                exit_mid = opening[i]
            elif times[i]-times[entry] >= 5*86400 or i-entry >= horizon:
                exit_mid = opening[i]
            elif low[i] <= stop:
                exit_mid = stop
            elif high[i] >= target:
                exit_mid = target
            if exit_mid >= 0:
                exit_fill = max(0.0,exit_mid-side_cost)
                exit_fee = max(minimum_fee,units*exit_fill*commission_rate)
                pnl = units*(exit_fill-fill)-entry_fee-exit_fee
                result[signal] = 1 if pnl > 0 else 0
                break
    return result


_labels_python = _labels
if njit is not None:
    _labels = njit(cache=True)(_labels)


def label_profitable_next_open(times,opening,high,low,close,pips,horizon,costs):
    return _labels(times,opening,high,low,close,pips,horizon,costs.side_price_cost,
                   costs.minimum_commission,costs.commission_bps/10000)
