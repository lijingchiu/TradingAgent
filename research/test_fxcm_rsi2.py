"""Synthetic integrity checks, not financial performance evidence."""
import gzip
import io
import json
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from research.fxcm_data import COLUMNS, read_archive, aggregate_minutes
from research.fxcm_rsi2 import FEATURES, inputs, fit_filter, apply_leaves, pattern_mask
from research.fxcm_rsi2_tailguard import signal_inputs


def minute_frame(count=30):
    t=pd.date_range("2017-01-02T07:00Z",periods=count,freq="1min")
    bid=1.1+np.sin(np.arange(count)/3)*.0002+np.arange(count)*.000002
    frame=pd.DataFrame({"time":t})
    for prefix,offset in (("Bid",0),("Ask",.00003)):
        for field,delta in (("Open",0),("High",.00008),("Low",-.00008),("Close",.00002)):
            frame[prefix+field]=bid+offset+delta
    return frame


class SourceTests(unittest.TestCase):
    def test_missing_minute_omits_only_incomplete_block(self):
        frame=minute_frame().drop(index=7).reset_index(drop=True)
        bars,quality=aggregate_minutes(frame,5)
        self.assertEqual(len(bars),5)
        self.assertEqual(quality["incomplete_blocks_omitted"],1)
        self.assertNotIn(pd.Timestamp("2017-01-02T07:05Z"),bars.time.tolist())

    def test_crossed_ask_does_not_drop_bid_exit_bar(self):
        frame=minute_frame()
        frame.loc[5,"AskOpen"]=frame.loc[5,"BidOpen"]-.00001
        bars,quality=aggregate_minutes(frame,5)
        self.assertEqual(len(bars),6)
        self.assertEqual(quality["crossed_open_bars_kept_but_entry_blocked"],1)
        self.assertLess(bars.iloc[1].AskOpen,bars.iloc[1].BidOpen)

    def test_invalid_geometry_is_counted_then_omitted(self):
        frame=minute_frame()
        frame.loc[3,"BidHigh"]=frame.loc[3,"BidLow"]-.001
        text=frame.drop(columns="time")
        text.insert(0,"DateTime",frame.time.dt.strftime("%m/%d/%Y %H:%M:%S.%f"))
        parsed,quality=read_archive(gzip.compress(text.to_csv(index=False).encode()))
        self.assertEqual(quality["invalid_ohlc_rows"],1)
        self.assertEqual(len(parsed),29)
        bars,_=aggregate_minutes(parsed,5)
        self.assertEqual(len(bars),5)

    def test_duplicate_and_off_grid_minutes_rejected(self):
        for duplicate in (True,False):
            frame=minute_frame()
            frame.loc[3,"time"]=frame.loc[2,"time"] if duplicate else frame.loc[3,"time"]+pd.Timedelta(seconds=1)
            text=frame.drop(columns="time")
            text.insert(0,"DateTime",frame.time.dt.strftime("%m/%d/%Y %H:%M:%S.%f"))
            with self.assertRaises(ValueError):
                read_archive(gzip.compress(text.to_csv(index=False).encode()))


class CausalityTests(unittest.TestCase):
    def setUp(self):
        self.frame=minute_frame(250)
        self.settings=dict(rsi_period=2,rsi_max=10,atr_period=14,atr_slow_period=30,ema_period=40,
                           ema_slope_bars=4,zscore_period=20,minimum_warmup_trading_bars=60,
                           minimum_atr_pips=1,stop_atr=4,target_atr=2,exit_rsi_at_least=80,
                           entry_hours_utc=[7,16],maximum_entry_spread_pips=2)

    def test_appended_future_prices_do_not_change_prefix(self):
        prefix=inputs(self.frame.iloc[:120].copy(),self.settings)
        modified=self.frame.copy()
        modified.loc[120:,COLUMNS]*=1.7
        entire=inputs(modified,self.settings)
        for key in ("x","entries","exits","stop","target","allowed"):
            np.testing.assert_allclose(prefix[key],entire[key][:120],equal_nan=True)

    def test_current_candle_extremes_do_not_enter_entry_features(self):
        original=inputs(self.frame,self.settings)
        modified=self.frame.copy()
        modified.loc[100,["BidHigh","BidLow","BidClose"]]=[2.,.2,1.8]
        changed=inputs(modified,self.settings)
        np.testing.assert_allclose(original["x"][100],changed["x"][100])
        self.assertEqual(original["allowed"][100],changed["allowed"][100])

    def test_current_crossed_quote_blocks_entry(self):
        modified=self.frame.copy()
        modified.loc[100,"AskOpen"]=modified.loc[100,"BidOpen"]-.00001
        changed=inputs(modified,self.settings)
        self.assertFalse(changed["allowed"][100])


class PatternTests(unittest.TestCase):
    def test_kept_leaves_require_positive_net_and_half_wins(self):
        x=np.zeros((220,len(FEATURES)))
        x[110:,0]=10
        trades=[dict(entry_index=i,units=1000,net_pnl=.2 if i>=110 else -.2,reason="target" if i>=110 else "stop") for i in range(220)]
        plan={"pattern_learning":{"minimum_samples_per_leaf":100,"random_state":20261004}}
        model=fit_filter(x,trades,2,plan)
        serialized=json.loads(json.dumps(model))
        kept=pattern_mask(x,serialized)
        self.assertFalse(kept[:110].any())
        self.assertTrue(kept[110:].all())
        for leaf in model["eligible_leaves"]:
            info=model["leaf_training_diagnostics"][str(leaf)]
            self.assertGreater(info["mean_net_pips"],0)
            self.assertGreaterEqual(info["win_rate"],.5)
        x[0,0]=np.nan
        self.assertEqual(apply_leaves(x,serialized)[0],-1)

    def test_too_small_training_sample_blocks_all_entries(self):
        x=np.zeros((1,len(FEATURES)))
        plan={"pattern_learning":{"minimum_samples_per_leaf":100,"random_state":20261004}}
        model=fit_filter(x,[],2,plan)
        self.assertTrue(model["disabled"])
        self.assertFalse(pattern_mask(x,model).any())


class TailguardCausalityTests(unittest.TestCase):
    def setUp(self):
        path=Path(__file__).resolve().parents[1]/"artifacts/intraday/fxcm_rsi2_tailguard/preregistration.json"
        self.plan=json.loads(path.read_text())
        self.plan["base_signal"].update(ema_period=40,atr_slow_period=30,ema_slope_bars=4,
                                      minimum_warmup_trading_bars=60,minimum_atr_pips=1)
        self.frame=minute_frame(250)

    def test_confirmation_and_compression_are_prefix_causal(self):
        modified=self.frame.copy()
        modified.loc[120:,COLUMNS]*=1.7
        for variant in self.plan["variants_per_base"]:
            with self.subTest(variant=variant):
                prefix=signal_inputs(self.frame.iloc[:120].copy(),self.plan,variant)
                future=signal_inputs(modified,self.plan,variant)
                for key in ("entries","exits","stop","target","x","allowed"):
                    np.testing.assert_allclose(prefix[key],future[key][:120],equal_nan=True)

    def test_execution_candle_cannot_change_confirmation_entry_features(self):
        changed=self.frame.copy()
        changed.loc[100,["BidHigh","BidLow","BidClose"]]=[2.,.2,1.8]
        for variant in self.plan["variants_per_base"]:
            with self.subTest(variant=variant):
                original=signal_inputs(self.frame,self.plan,variant)
                modified=signal_inputs(changed,self.plan,variant)
                np.testing.assert_allclose(original["x"][100],modified["x"][100])
                self.assertEqual(original["allowed"][100],modified["allowed"][100])

    def test_unregistered_variant_is_rejected(self):
        with self.assertRaises(ValueError):
            signal_inputs(self.frame,self.plan,"tune_after_validation")


if __name__ == "__main__":
    unittest.main()
