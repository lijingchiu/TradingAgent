"""Completed-bar-only stationary features; no clock-derived predictors."""
import numpy as np
import pandas as pd


def features(opens, highs, lows, closes):
    opening, high, low, close = [pd.Series(np.asarray(values,dtype=float)) for values in (opens,highs,lows,closes)]
    log_close = np.log(close)
    ret = log_close.diff()
    tr = pd.concat([high-low,(high-close.shift()).abs(),(low-close.shift()).abs()],axis=1).max(axis=1)
    atr14 = tr.rolling(14,min_periods=14).mean()
    atr96 = tr.rolling(96,min_periods=96).mean()
    columns = {}
    for lag in (1,2,4,8,16,32,64,96):
        columns[f'return_{lag}'] = log_close.diff(lag)
    for lag in (1,2,3):
        columns[f'prior_return_{lag}'] = ret.shift(lag)
    for window in (8,32,96):
        columns[f'vol_{window}'] = ret.rolling(window,min_periods=window).std()
        columns[f'return_mean_{window}'] = ret.rolling(window,min_periods=window).mean()
    for window in (20,96):
        average = close.rolling(window,min_periods=window).mean()
        deviation = close.rolling(window,min_periods=window).std()
        columns[f'zscore_{window}'] = (close-average)/deviation.replace(0,np.nan)
        columns[f'ema_distance_{window}'] = (close-close.ewm(span=window,adjust=False).mean())/atr14.replace(0,np.nan)
    columns['atr14_pips'] = atr14/.0001
    columns['atr96_pips'] = atr96/.0001
    columns['atr_ratio'] = atr14/atr96.replace(0,np.nan)
    for lag in (4,16,64):
        columns[f'move_by_atr_{lag}'] = close.diff(lag)/atr14.replace(0,np.nan)
    width = (high-low).replace(0,np.nan)
    columns['body_by_range'] = (close-opening)/width
    columns['close_location'] = (close-low)/width
    columns['range_ratio'] = (high-low)/atr14.replace(0,np.nan)
    low96,high96 = low.rolling(96).min(),high.rolling(96).max()
    columns['range_location96'] = (close-low96)/(high96-low96).replace(0,np.nan)
    frame = pd.DataFrame(columns).replace([np.inf,-np.inf],np.nan)
    # Undefined zero-volatility measurements are unavailable, never inferred from future bars.
    matrix = np.ascontiguousarray(frame.to_numpy(dtype=np.float64))
    valid = np.isfinite(matrix).all(axis=1)
    valid[:192] = False
    return matrix,valid,list(frame.columns)
