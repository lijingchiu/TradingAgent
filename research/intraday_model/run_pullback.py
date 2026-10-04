"""Evaluate the preregistered regime-pullback family, never final prices."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import argparse
import numpy as np

from research.intraday_engine import run_intraday_backtest
from research.intraday_model.run_research import load_data,epoch,stability
from research.intraday_model.pullback_signals import common_features,candidate_signals
from trading_agent.risk import DEFAULT_COSTS

ROOT=Path(__file__).resolve().parents[2]
FOLDER=ROOT/'artifacts/intraday/model'


def run(arrays,signals,config,capital,first,last,costs=DEFAULT_COSTS):
    return run_intraday_backtest(*arrays,signals,config['stop_pips']*.0001,
        config['target_pips']*.0001,quote_kind='bid',max_signal_age_seconds=900,
        max_holding_bars=config['max_holding_bars'],max_holding_days=5,
        costs=costs,initial_equity=capital,start_index=first,end_index=last,
        include_trades=True,include_equity_curve=False)


def eligible(row):
    a,b=[row[key]['summary'] for key in ('development','validation')]
    return bool(a['net_profit']>0 and b['net_profit']>0 and a['win_rate']>=.5 and b['win_rate']>=.5
        and a['eligible_trades']+b['eligible_trades']>=500
        and a['risk_breaches']==b['risk_breaches']==0
        and a['max_trade_peak_drawdown_equity_fraction']<=.01
        and b['max_trade_peak_drawdown_equity_fraction']<=.01)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--data',type=Path,default=ROOT/'data/intraday/dukascopy_eurusd_bid_development_2015_2021_m15.csv')
    parser.add_argument('--output-name',default='pullback_direct_bid_devval')
    args=parser.parse_args()
    registered=FOLDER/'pullback_preregistration.json'
    registration=json.loads(registered.read_text())
    arrays=load_data(args.data,'bid')
    times=arrays[0]
    if times[-1]>=epoch('2022-01-01'):raise ValueError('Do not evaluate final outcomes')
    common=common_features(arrays[4])
    splits={name:tuple(map(int,np.searchsorted(times,[epoch(start),epoch(end)])))
            for name,start,end in [('development','2015-01-01','2018-01-01'),('validation','2018-01-01','2022-01-01')]}
    out=FOLDER/(args.output_name+'.json')
    report={'symbol':'EURUSD','timeframe':'M15','quote_kind':'bid','source_calendar':'UTC',
        'data_path':str(args.data),'data_sha256':hashlib.sha256(args.data.read_bytes()).hexdigest(),
        'preregistration_sha256':hashlib.sha256(registered.read_bytes()).hexdigest(),
        'software_hashes':{path.name:hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(Path(__file__).parent.glob('*.py'))},
        'holdout_evaluated':False,'candidates':[],'baselines':[],
        'declared_signal_configurations':24,'declared_operating_capital_variants':48,
        'baselines_declared':12,'complete':False}
    for capital in registration['capital_scenarios']:
        for config in registration['candidates']:
            signals=candidate_signals(common,config)
            row={'config':config,'initial_equity':capital}
            for split,(first,last) in splits.items():
                split_signals=signals.copy();split_signals[:first]=False;split_signals[last:]=False
                result=run(arrays,split_signals,config,capital,first,last)
                row[split]={'summary':result['summary'],'stability':stability(result['trades']),
                            'completed_bar_signal_count':int(split_signals.sum())}
            row['eligible']=eligible(row)
            report['candidates'].append(row)
            a,b=[row[key]['summary'] for key in ('development','validation')]
            print(config['name'],capital,'dev',a['eligible_trades'],round(a['win_rate'],4),round(a['net_profit'],2),
                  'val',b['eligible_trades'],round(b['win_rate'],4),round(b['net_profit'],2),'eligible',row['eligible'],flush=True)
        # Untuned controls use the same signal-independent exit policy.
        for stop in (50,80):
            for target in (20,30,50):
                config={'stop_pips':stop,'target_pips':target,'max_holding_bars':96 if stop==50 else 192}
                row={'name':'always_long','config':config,'initial_equity':capital}
                for split,(first,last) in splits.items():
                    signals=np.ones(len(times),dtype=bool);signals[:max(first,4608)]=False;signals[last:]=False
                    result=run(arrays,signals,config,capital,first,last)
                    row[split]={'summary':result['summary'],'stability':stability(result['trades'])}
                report['baselines'].append(row)
        out.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    candidates=[row for row in report['candidates'] if row['eligible']]
    ranked=sorted(candidates,key=lambda row:(-min(row['development']['summary']['net_return'],row['validation']['summary']['net_return']),
        -row['validation']['summary']['net_return'],row['initial_equity'],row['config']['name']))
    report.update(complete=True,eligible_candidates=len(candidates),candidates_evaluated=len(report['candidates']),
        best_candidate={'config':ranked[0]['config'],'initial_equity':ranked[0]['initial_equity']} if ranked else None)
    out.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    print('SAVED',out,'eligible',len(candidates),flush=True)


if __name__=='__main__':main()
