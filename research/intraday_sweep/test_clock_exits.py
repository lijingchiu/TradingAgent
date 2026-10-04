"""Deadlines must use the current executable quote after a missing bar."""
import unittest
import numpy as np
import pandas as pd
from research.intraday_sweep.fixing import candidates, signals
from research.intraday_mean_reversion.session_study import SessionConfig, signals as session_signals


def frame(stamps):
    time=pd.to_datetime(stamps,utc=True)
    return pd.DataFrame(dict(timestamp=time.astype(str),time=time,open=1.1,
                             high=1.101,low=1.099,close=1.099))


class ClockExitTests(unittest.TestCase):
    def test_fixing_gap_across_deadline_closes_at_next_actual_quote(self):
        source=frame(['2020-01-06T16:00Z','2020-01-06T16:15Z',
                      '2020-01-06T17:00Z','2020-01-07T16:00Z'])
        config=next(c for c in candidates() if c['session']=='london1615')
        _,_,exits=signals(source,config)
        self.assertTrue(exits[2])

    def test_london_deadline_tracks_dst(self):
        config=next(c for c in candidates() if c['session']=='london1615')
        for stamps in (['2020-01-06T18:00Z','2020-01-06T18:15Z'],
                       ['2020-07-06T17:00Z','2020-07-06T17:15Z']):
            self.assertTrue(signals(frame(stamps),config)[2][0])

    def test_session_gap_into_following_morning_cannot_restart_clock(self):
        config=SessionConfig(session='london08',filter='unconditional',hours=2,stop_pips=40,target_pips=20)
        source=frame(['2020-01-06T08:00Z','2020-01-06T09:00Z','2020-01-07T08:00Z'])
        self.assertTrue(session_signals(source,config)[2][1])

    def test_future_price_suffix_cannot_change_clock_or_flow_prefix(self):
        source=frame(pd.date_range('2020-07-06T12:00Z',periods=32,freq='15min'))
        config=next(c for c in candidates() if c['session']=='london1615')
        changed=source.copy(); changed.loc[24:,'close']=2
        first=signals(source,config); second=signals(changed,config)
        for a,b in zip(first,second): np.testing.assert_array_equal(a[:23],b[:23])
