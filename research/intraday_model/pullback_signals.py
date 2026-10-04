"""Completed rebound after a deep dip in a multiday bullish M15 regime."""
import numpy as np
import pandas as pd

try:
    from numba import njit
except ImportError:
    njit=None


def _wilder_rsi2(closes):
    n=len(closes)
    rsi=np.full(n,np.nan,dtype=np.float64)
    if n<3:return rsi
    gain=0.0;loss=0.0
    for i in range(1,n):
        change=closes[i]-closes[i-1]
        g=max(change,0.0);l=max(-change,0.0)
        if i<=2:
            gain+=g/2;loss+=l/2
        else:
            gain=(gain+g)/2;loss=(loss+l)/2
        if i>=2:
            rsi[i]=50.0 if gain==loss==0 else 100.0 if loss==0 else 100.0-100.0/(1.0+gain/loss)
    return rsi


def _armed_signals(rsi,bullish,dip,rebound,expiry,warmup):
    signals=np.zeros(len(rsi),dtype=np.bool_)
    armed=-1
    for i in range(len(rsi)):
        if i<warmup or not bullish[i] or not np.isfinite(rsi[i]):
            armed=-1
            continue
        if rsi[i]<=dip:
            armed=i
            continue
        if armed>=0:
            if i-armed>expiry:
                armed=-1
            elif i>armed and rsi[i-1]<rebound<=rsi[i]:
                signals[i]=True
                armed=-1
    return signals


if njit is not None:
    _wilder_rsi2=njit(cache=True)(_wilder_rsi2)
    _armed_signals=njit(cache=True)(_armed_signals)


def common_features(closes):
    close=pd.Series(np.asarray(closes,dtype=float))
    fast=close.ewm(span=384,adjust=False).mean()
    slow=close.ewm(span=1536,adjust=False).mean()
    bullish=((fast>slow) & (slow>slow.shift(96))).to_numpy(dtype=bool)
    bullish[:4608]=False
    return {'rsi':_wilder_rsi2(close.to_numpy()),'bullish':np.ascontiguousarray(bullish)}


def candidate_signals(common,config):
    return _armed_signals(common['rsi'],common['bullish'],config['dip_threshold'],
        config['rebound_threshold'],config['armed_expiry_bars'],config['warmup_bars'])
