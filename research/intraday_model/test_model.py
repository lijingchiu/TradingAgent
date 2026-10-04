"""Small financial-integrity checks; no market outcomes are evaluated here."""
import unittest
import numpy as np

from research.intraday_engine import run_intraday_backtest
from research.intraday_model.features import features
from research.intraday_model.labels import label_profitable_next_open
from trading_agent.risk import DEFAULT_COSTS


class ModelIntegrityTests(unittest.TestCase):
    def setUp(self):
        rng=np.random.default_rng(20261004)
        self.n=600
        self.close=1.1+np.cumsum(rng.normal(0,.0005,self.n))
        self.open=np.r_[self.close[0],self.close[:-1]]
        self.high=np.maximum(self.open,self.close)+rng.uniform(0,.0003,self.n)
        self.low=np.minimum(self.open,self.close)-rng.uniform(0,.0003,self.n)
        self.times=1600000000+np.arange(self.n)*900

    def test_completed_features_do_not_depend_on_future(self):
        x,valid,names=features(self.open,self.high,self.low,self.close)
        prices=[values.copy() for values in (self.open,self.high,self.low,self.close)]
        for values in prices: values[401:]+=1
        changed,_,_=features(*prices)
        np.testing.assert_array_equal(x[:401],changed[:401])
        self.assertFalse(any(valid[:192]))
        self.assertFalse(any('hour' in name or 'weekday' in name for name in names))

    def test_labels_match_mid_and_bid_shared_execution(self):
        for quote_kind in ('mid','bid'):
            raw=(self.open,self.high,self.low,self.close)
            offset=DEFAULT_COSTS.spread_pips*.0001/2 if quote_kind=='bid' else 0
            label_prices=[values+offset for values in raw]
            for pips,horizon in ((20,96),(30,192)):
                labels=label_profitable_next_open(self.times,*label_prices,pips,horizon,DEFAULT_COSTS)
                for signal in (205,251,303):
                    entries=np.zeros(self.n,dtype=bool);entries[signal]=True
                    result=run_intraday_backtest(self.times,*raw,entries,pips*.0001,pips*.0001,
                        max_holding_bars=horizon,start_index=signal+1,end_index=signal+horizon+2,
                        include_trades=True,quote_kind=quote_kind)
                    self.assertEqual(len(result['trades']),1)
                    self.assertEqual(labels[signal],int(result['trades'][0]['net_pnl']>0))
                    self.assertLessEqual(result['summary']['max_funded_loss_equity_fraction'],.01)
                    self.assertEqual(result['summary']['risk_breaches'],0)

    def test_stale_signal_is_neither_training_label_nor_trade(self):
        times=self.times.copy();times[206:]+=86400
        labels=label_profitable_next_open(times,self.open,self.high,self.low,self.close,20,96,DEFAULT_COSTS)
        self.assertEqual(labels[205],-1)
        signals=np.zeros(self.n,dtype=bool);signals[205]=True
        result=run_intraday_backtest(times,self.open,self.high,self.low,self.close,signals,.002,.002,
            max_holding_bars=96,max_signal_age_seconds=900,start_index=206,end_index=304)
        self.assertEqual(result['summary']['closed_trades'],0)
        self.assertEqual(result['summary']['stale_signal_entries_rejected'],1)

    def test_pullback_requires_prior_dip_and_completed_rebound(self):
        from research.intraday_model.pullback_signals import _armed_signals
        rsi=np.array([60.,4.,10.,19.,25.,60.,4.,19.,31.])
        regime=np.ones(len(rsi),dtype=bool)
        actual=_armed_signals(rsi,regime,5,20,24,0)
        np.testing.assert_array_equal(np.flatnonzero(actual),[4,8])
        regime[3]=False
        canceled=_armed_signals(rsi,regime,5,20,24,0)
        np.testing.assert_array_equal(np.flatnonzero(canceled),[8])


if __name__=='__main__':
    unittest.main()
