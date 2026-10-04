"""Mechanical checks of the preregistered later futures snapshot, never strategy P&L."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
FOLDER=ROOT/'data/intraday/futures_reserved_yahoo'
PROTOCOL=ROOT/'artifacts/intraday/futures_additional_reserved_protocol.json'


def inspect(path):
    frame=pd.read_csv(path)
    stamp=pd.to_datetime(frame.timestamp,utc=True)
    epoch=stamp.astype('int64').to_numpy()//10**9
    prices=frame[['open','high','low','close']].to_numpy(float)
    bad=(~np.isfinite(prices).all(axis=1))|(prices.min(axis=1)<=0)
    bad |= (frame.high<frame[['open','close','low']].max(axis=1)).to_numpy()
    bad |= (frame.low>frame[['open','close','high']].min(axis=1)).to_numpy()
    tick=np.isclose(prices/.25,np.round(prices/.25),atol=1e-8,rtol=0).all(axis=1)
    local=stamp.dt.tz_convert('America/New_York')
    sessions=np.array([d+timedelta(days=1) if h>=18 else d
                       for d,h in zip(local.dt.date,local.dt.hour)])
    records=[]
    for day in sorted(set(sessions)):
        if not pd.Timestamp('2026-07-01').date()<=day<pd.Timestamp('2026-08-12').date(): continue
        index=np.flatnonzero(sessions==day)
        good=(~bad[index])&tick[index]&(frame.volume.to_numpy()[index]>0)
        start=int(pd.Timestamp(str(day),tz='America/New_York').timestamp())-6*3600
        expected=start+np.arange(276)*300
        complete=np.array_equal(epoch[index][good],expected)
        excluded=str(day) in ['2026-07-01','2026-07-03']
        records.append(dict(date=str(day),observations=len(index),
                            positive_volume_valid_observations=int(good.sum()),
                            complete_276=bool(complete),excluded_policy=excluded,
                            eligible_source_session=bool(complete and not excluded)))
    return dict(symbol=path.name.split('_')[0],file=str(path.relative_to(ROOT)),
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(),rows=len(frame),
                first_timestamp=stamp.iloc[0].isoformat(),last_timestamp=stamp.iloc[-1].isoformat(),
                invalid_ohlc=int(bad.sum()),off_tick_rows=int((~tick).sum()),
                duplicates=int(stamp.duplicated().sum()),
                nonincreasing_timestamps=int((np.diff(epoch)<=0).sum()),
                off_native_grid=int((epoch%300!=0).sum()),
                zero_or_negative_volume=int((frame.volume<=0).sum()),
                sessions=records,complete_eligible_sessions=sum(r['eligible_source_session'] for r in records),
                exclusions_are_source_quality_only=True,strategy_features_or_pnl_evaluated=False,
                source_limitations=['Yahoo continuousroot nativeexpiry/BBO/actualfees unverified',
                    'Publisher drops missing/duplicate rows before CSV; original rawAPI response absent',
                    'ExplicitNYoffset timestamps; modeledbar-start convention not independently certified',
                    'No syntheticsample or publisherbacktest log inspected'])


def main():
    plan=json.loads(PROTOCOL.read_text())
    sources=[]
    for source in plan['sources']:
        path=FOLDER/Path(source['path']).name
        raw=path.read_bytes()
        blob_hash=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
        if blob_hash!=source['git_blob_sha']: raise ValueError('Pinned source blob changed')
        sources.append(inspect(path))
    report=dict(checked_at_utc=datetime.now(timezone.utc).isoformat(),
                registered_protocol=str(PROTOCOL.relative_to(ROOT)),
                protocol_sha256=hashlib.sha256(PROTOCOL.read_bytes()).hexdigest(),
                sources=sources,strategy_features_or_pnl_evaluated=False)
    (FOLDER/'source_quality_receipt.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({r['symbol']:r['complete_eligible_sessions'] for r in sources}))


if __name__=='__main__': main()
