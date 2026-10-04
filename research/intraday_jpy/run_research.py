"""24 declared USDJPY strategies; JPY-denominated ledger; no final outcomes."""
from collections import defaultdict
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import math
import numpy as np
import pandas as pd

from research.intraday_engine import run_intraday_backtest
from research.intraday_model.pullback_signals import common_features,candidate_signals
from trading_agent.risk import CostModel

ROOT=Path(__file__).resolve().parents[2]
FOLDER=ROOT/'artifacts/intraday/jpy'


def epoch(date):
 return int(datetime.fromisoformat(date).replace(tzinfo=timezone.utc).timestamp())


def load_source(registration):
 path=FOLDER/'source_usdjpy_m15_raw.csv'
 raw=pd.read_csv(path)
 parsed=pd.to_datetime(raw['Date'])
 # Exclude all2022prices before any price-based feature, summary or strategy evaluation.
 mask=(parsed>=pd.Timestamp('2014-10-01')) & (parsed<pd.Timestamp('2022-01-01'))
 frame=raw.loc[mask].copy();parsed=parsed.loc[mask]
 values=frame[['open','high','low','close']].to_numpy(dtype=float)/registration['price_divisor']
 valid=np.isfinite(values).all(axis=1) & (values>0).all(axis=1)
 valid &= (values[:,2]<=np.minimum(values[:,0],values[:,3])) & (values[:,1]>=np.maximum(values[:,0],values[:,3])) & (values[:,2]<=values[:,1])
 duplicate=parsed.duplicated(keep='first').to_numpy()
 invalid=int((~valid).sum());duplicates=int(duplicate.sum())
 keep=valid & ~duplicate
 frame=frame.loc[keep].copy();parsed=parsed.loc[keep];values=values[keep]
 order=np.argsort(parsed.to_numpy());unsorted=int(np.count_nonzero(np.diff(parsed.astype('int64').to_numpy())<=0))
 parsed=parsed.iloc[order];values=values[order]
 close=values[:,3]
 if not (70<float(np.median(close))<150 and np.quantile(close,.01)>60 and np.quantile(close,.99)<160):
  raise ValueError('USDJPY scaling does not produce plausible JPY per USD quotes')
 # Epoch encoding provides chronological source-calendar intervals only; no UTC session claim.
 times=np.ascontiguousarray(parsed.astype('int64').to_numpy()//1_000_000_000,dtype=np.int64)
 arrays=(times,*(np.ascontiguousarray(values[:,column]) for column in range(4)))
 normalized=pd.DataFrame({'timestamp':parsed.dt.strftime('%Y-%m-%dT%H:%M:%S').to_numpy(),**{name:values[:,i]for i,name in enumerate(['open','high','low','close'])}})
 output=FOLDER/'usdjpy_m15_pre2022.csv';normalized.to_csv(output,index=False)
 provenance={'source_url':registration['source_url'],'pinned_commit':registration['source_pinned_commit'],
  'raw_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'normalized_sha256':hashlib.sha256(output.read_bytes()).hexdigest(),
  'raw_rows':len(raw),'research_rows':len(times),'invalid_rows_excluded':invalid,'duplicates_excluded':duplicates,
  'unsorted_transitions':unsorted,'price_divisor':1000,'price_unit':'JPY per USD',
  'first_research_timestamp':str(parsed.iloc[0]),'last_research_timestamp':str(parsed.iloc[-1]),
  'price_min':float(close.min()),'price_max':float(close.max()),'price_median':float(np.median(close)),
  'timezone':'UNKNOWN; naive source calendar, no clock/session features','quote_side':'UNKNOWN; assumed indicative-mid scenario',
  'currency_metadata':'Account, principal, costs and PnL are JPY; integer holding units are USD',
  'conversion_assumption':'Publisher integerlike quote points divided by1000, consistent with3decimal JPY FX quote precision and plausible source-period USDJPY prices. Original broker scaling metadata is unavailable.'}
 (FOLDER/'source_provenance.json').write_text(json.dumps(provenance,indent=2)+'\n')
 return arrays,provenance


def stability(trades):
 groups=defaultdict(list)
 for trade in trades:
  if trade['reason']=='sample_end':continue
  month=datetime.fromtimestamp(trade['exit_time'],timezone.utc).strftime('%Y-%m')
  groups[month].append(trade['net_pnl'])
 rows=[{'month':key,'trades':len(values),'net_profit_jpy':float(sum(values)),
         'win_rate':sum(value>0 for value in values)/len(values)}for key,values in sorted(groups.items())]
 annual=defaultdict(float)
 for row in rows:annual[row['month'][:4]]+=row['net_profit_jpy']
 return {'monthly':rows,'annual_net_profit_jpy':dict(annual),
  'positive_months':sum(row['net_profit_jpy']>0 for row in rows),'negative_months':sum(row['net_profit_jpy']<0 for row in rows),
  'calendar_note':'Mirror source-calendar labels; no claim these are UTC trading days.'}


def evaluate(arrays,signals,config,costs,capital,first,last):
 result=run_intraday_backtest(*arrays,signals,config['stop_pips']*costs.pip_size,
  config['target_pips']*costs.pip_size,costs=costs,initial_equity=capital,
  max_holding_bars=config['max_holding_bars'],max_holding_days=5,max_signal_age_seconds=900,
  quote_kind='mid',start_index=first,end_index=last,include_trades=True)
 result['summary']['account_currency']='JPY'
 result['summary']['holding_currency_units']='USD'
 return result


def eligible(row):
 a,b=[row[name]['summary']for name in ('development','validation')]
 return bool(a['net_profit']>0 and b['net_profit']>0 and a['win_rate']>=.5 and b['win_rate']>=.5
  and a['eligible_trades']+b['eligible_trades']>=500 and a['risk_breaches']==b['risk_breaches']==0
  and a['max_trade_peak_drawdown_equity_fraction']<=.01 and b['max_trade_peak_drawdown_equity_fraction']<=.01)


def main():
 path=FOLDER/'preregistration.json';registration=json.loads(path.read_text())
 arrays,provenance=load_source(registration);times=arrays[0]
 if times[-1]>=epoch('2022-01-01'):raise ValueError('Only pre2022 research outcomes allowed')
 costs=CostModel(**registration['cost_model']);capital=registration['initial_equity']
 common=common_features(arrays[4])
 splits={name:tuple(map(int,np.searchsorted(times,[epoch(start),epoch(end)])))for name,start,end in
  [('development','2015-01-01','2018-01-01'),('validation','2018-01-01','2022-01-01')]}
 report={'symbol':'USDJPY','timeframe':'M15','account_currency':'JPY','initial_equity_jpy':capital,
  'preregistration_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'provenance':provenance,
  'candidates':[],'baselines':[],'holdout_evaluated':False,'complete':False,
  'software_hashes':{p.name:hashlib.sha256(p.read_bytes()).hexdigest()for p in Path(__file__).parent.glob('*.py')},
  'shared_signal_sha256':hashlib.sha256((ROOT/'research/intraday_model/pullback_signals.py').read_bytes()).hexdigest(),
  'shared_engine_sha256':hashlib.sha256((ROOT/'research/intraday_engine.py').read_bytes()).hexdigest()}
 for config in registration['candidates']:
  signals=candidate_signals(common,config);row={'config':config}
  for split,(first,last) in splits.items():
   entries=signals.copy();entries[:first]=False;entries[last:]=False
   result=evaluate(arrays,entries,config,costs,capital,first,last)
   row[split]={'summary':result['summary'],'stability':stability(result['trades'])}
  row['eligible']=eligible(row);report['candidates'].append(row)
  a,b=[row[name]['summary']for name in ('development','validation')]
  print(config['name'],'dev',a['eligible_trades'],round(a['win_rate'],4),round(a['net_profit'],1),
   'val',b['eligible_trades'],round(b['win_rate'],4),round(b['net_profit'],1),'JPY eligible',row['eligible'],flush=True)
 for stop in (50,80):
  for target in (20,30,50):
   config={'stop_pips':stop,'target_pips':target,'max_holding_bars':96 if stop==50 else 192}
   row={'name':'always_long','config':config}
   for split,(first,last) in splits.items():
    signals=np.ones(len(times),dtype=bool);signals[:max(first,4608)]=False;signals[last:]=False
    result=evaluate(arrays,signals,config,costs,capital,first,last)
    row[split]={'summary':result['summary'],'stability':stability(result['trades'])}
   report['baselines'].append(row)
 qualified=[row for row in report['candidates']if row['eligible']]
 ranked=sorted(qualified,key=lambda row:(-min(row['development']['summary']['net_return'],row['validation']['summary']['net_return']),
  -row['validation']['summary']['net_return'],row['config']['name']))
 report.update(complete=True,candidates_evaluated=len(report['candidates']),eligible_candidates=len(qualified),
  best_candidate=ranked[0]['config']if ranked else None,
  interpretation='Only provisional broker-mirror development/validation. All money amounts are JPY, not USD. No final outcomes inspected. Authentic quote-side/timezone data required before final or paper use.')
 out=FOLDER/'usdjpy_mirror_devval.json';out.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
 print('SAVED',out,'eligible',len(qualified),flush=True)


if __name__=='__main__':main()
