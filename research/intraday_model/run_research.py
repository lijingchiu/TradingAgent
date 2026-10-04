"""Evaluate a bounded ML family on pre-2022 prices only; never final holdout."""
from collections import defaultdict
from datetime import datetime,timezone
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

import joblib
import sklearn
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier,RandomForestClassifier
from sklearn.metrics import roc_auc_score,brier_score_loss

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from research.intraday_engine import run_intraday_backtest
from research.intraday_model.features import features
from research.intraday_model.labels import label_profitable_next_open
from trading_agent.risk import DEFAULT_COSTS

ROOT=Path(__file__).resolve().parents[2]
FOLDER=ROOT/'artifacts/intraday/model'


def epoch(date):
    return int(datetime.fromisoformat(date).replace(tzinfo=timezone.utc).timestamp())


def load_data(path,quote_side):
    frame=pd.read_csv(path)
    times=pd.to_datetime(frame['timestamp'],utc=True)
    # Conversion to epoch is only for ordering/elapsed source-calendar time on a naive mirror;
    # it does not assert the source timezone or create UTC session features.
    keep=(times>=pd.Timestamp('2014-10-01',tz='UTC')) & (times<pd.Timestamp('2022-01-01',tz='UTC'))
    frame=frame.loc[keep]
    times=times.loc[keep].astype('int64').to_numpy()//1_000_000_000
    arrays=[np.ascontiguousarray(frame[column].to_numpy(dtype=float)) for column in ('open','high','low','close')]
    # Raw BID stays raw for stationary features; engine quote_kind applies assumed spread.
    if not len(times) or times[-1]>=epoch('2022-01-01'):
        raise ValueError('No final-price evaluation is permitted')
    return (np.ascontiguousarray(times,dtype=np.int64),*arrays)


def stability(trades):
    monthly=defaultdict(list)
    daily=defaultdict(list)
    for trade in trades:
        if trade['reason']=='sample_end': continue
        date=datetime.fromtimestamp(trade['exit_time'],timezone.utc)
        monthly[date.strftime('%Y-%m')].append(trade['net_pnl'])
        daily[date.strftime('%Y-%m-%d')].append(trade['net_pnl'])
    rows=[{'month':key,'trades':len(values),'net_profit':float(sum(values)),
           'win_rate':float(sum(value>0 for value in values)/len(values))}
          for key,values in sorted(monthly.items())]
    annual=defaultdict(float)
    for row in rows: annual[row['month'][:4]]+=row['net_profit']
    return {'positive_months':sum(row['net_profit']>0 for row in rows),
            'negative_months':sum(row['net_profit']<0 for row in rows),
            'trading_months':len(rows),'monthly':rows,'annual_net_profit':dict(annual),
            'daily':[{'date':key,'net_profit':float(sum(values)),'closed_trades':len(values)} for key,values in sorted(daily.items())],
            'calendar_note':'Dates follow the documented source-calendar convention; naive mirror labels are not authenticated UTC trading sessions.'}


def model_for(name,registration):
    return {'hist_gradient_boosting':HistGradientBoostingClassifier,
            'random_forest':RandomForestClassifier}[name](**registration['models'][name])


def fit_model(name,matrix,valid,labels,times,train_end,registration):
    embargo=registration['purge_embargo_bars']
    first,last=np.searchsorted(times,[epoch('2015-01-01'),epoch(train_end)])
    last=max(first,last-embargo-1) # One extra bar reserves causal next-open entry plus full label horizon.
    indices=np.arange(len(times))
    mask=valid & (labels>=0) & (indices>=first) & (indices<last) & (indices%4==0)
    if mask.sum()<1000 or len(np.unique(labels[mask]))<2:
        raise ValueError('Insufficient two-class training observations')
    model=model_for(name,registration)
    started=time.monotonic()
    model.fit(matrix[mask],labels[mask])
    return model,{'rows':int(mask.sum()),'last_signal_epoch':int(times[np.flatnonzero(mask)[-1]]),
                  'train_label_positive_fraction':float(labels[mask].mean()),'seconds':round(time.monotonic()-started,3)}


def predict_period(model,matrix,valid,times,start,end,embargo):
    first,last=np.searchsorted(times,[epoch(start),epoch(end)])
    first=min(last,first+embargo)
    indices=np.arange(len(times))
    mask=valid & (indices>=first) & (indices<last)
    scores=np.zeros(len(times),dtype=np.float64)
    scores[mask]=model.predict_proba(matrix[mask])[:,1]
    return scores,mask,int(first),int(last)


def evaluate(arrays,signals,config,first,last,include_trades=True,quote_kind='mid'):
    return run_intraday_backtest(*arrays,signals,config['stop_pips']*.0001,
        config['target_pips']*.0001,max_holding_bars=config['horizon_bars'],
        max_holding_days=5,max_signal_age_seconds=900,costs=DEFAULT_COSTS,initial_equity=100000,
        start_index=first,end_index=last,include_trades=include_trades,include_equity_curve=False,
        **({'quote_kind':'bid'} if quote_kind=='bid' else {}))


def passes(result,registration):
    development,validation=[result[key]['summary'] for key in ('development','validation')]
    rule=registration['selection_eligibility']
    return bool(development['net_profit']>0 and validation['net_profit']>0
        and development['win_rate']>=.5 and validation['win_rate']>=.5
        and development['eligible_trades']>=rule['development_natural_trades_gte']
        and validation['eligible_trades']>=rule['validation_natural_trades_gte']
        and development['risk_breaches']==validation['risk_breaches']==0
        and development['max_trade_peak_drawdown_equity_fraction']<=.01
        and validation['max_trade_peak_drawdown_equity_fraction']<=.01)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--data',type=Path,required=True)
    parser.add_argument('--symbol',choices=('EURUSD','GBPUSD'),required=True)
    parser.add_argument('--source',required=True)
    parser.add_argument('--quote-side',choices=('indicative_mid_unknown','bid','mid'),default='indicative_mid_unknown')
    parser.add_argument('--output-name',default='mirror_devval')
    args=parser.parse_args()
    registration_path=FOLDER/'preregistration.json'
    registration=json.loads(registration_path.read_text())
    arrays=load_data(args.data,args.quote_side)
    times,opening,high,low,close=arrays
    matrix,valid,feature_names=features(opening,high,low,close)
    summaries=[]
    baselines=[]
    model_records=[]
    # Reports checkpoint after every declared model/barrier so interruption cannot hide failures.
    output=FOLDER/(args.symbol.lower()+'_'+args.output_name+'.json')
    report={'symbol':args.symbol,'source':args.source,'quote_side':args.quote_side,
            'data_path':str(args.data),'data_sha256':hashlib.sha256(args.data.read_bytes()).hexdigest(),
            'preregistration_sha256':hashlib.sha256(registration_path.read_bytes()).hexdigest(),
            'feature_names':feature_names,'candidate_count_declared':12,
            'holdout_evaluated':False,'sklearn_version':sklearn.__version__,
            'software_hashes':{path.name:hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(Path(__file__).parent.glob('*.py'))},
            'models':model_records,'candidates':summaries,'baselines':baselines,
            'complete':False}
    for pips,horizon in ((20,96),(30,192)):
        label_arrays = arrays if args.quote_side!='bid' else (times,*(values+DEFAULT_COSTS.spread_pips*.0001/2 for values in arrays[1:]))
        labels=label_profitable_next_open(*label_arrays,pips,horizon,DEFAULT_COSTS)
        baseline_config={'stop_pips':pips,'target_pips':pips,'horizon_bars':horizon}
        for baseline_name,baseline_signals in [('always_long',valid),('momentum16_positive',valid & (matrix[:,4]>0))]:
            row={'name':baseline_name,'config':baseline_config}
            for split,start,end in [('development','2017-01-01','2018-01-01'),('validation','2018-01-01','2022-01-01')]:
                first,last=np.searchsorted(times,[epoch(start),epoch(end)])
                first=min(last,first+192)
                signals=baseline_signals.copy(); signals[:first]=False; signals[last:]=False
                run=evaluate(arrays,signals,baseline_config,int(first),int(last),quote_kind='bid' if args.quote_side=='bid' else 'mid')
                row[split]={'summary':run['summary'],'stability':stability(run['trades'])}
            baselines.append(row)
        for name in registration['models']:
            scores={}
            fits={}
            for split,train_end,start,end in [('development','2017-01-01','2017-01-01','2018-01-01'),('validation','2018-01-01','2018-01-01','2022-01-01')]:
                model,fit=fit_model(name,matrix,valid,labels,times,train_end,registration)
                score,mask,first,last=predict_period(model,matrix,valid,times,start,end,192)
                auc_mask=mask & (labels>=0)
                diagnostics={'roc_auc':float(roc_auc_score(labels[auc_mask],score[auc_mask])),
                    'brier_score':float(brier_score_loss(labels[auc_mask],score[auc_mask])),
                    'prediction_rows':int(mask.sum()),'training':fit}
                scores[split]=(score,mask,first,last)
                fits[split]=diagnostics
                # This model stays research-only; its training data ends before2022.
                if split=='validation':
                    model_path=FOLDER/f'{args.symbol.lower()}_{args.output_name}_{name}_b{pips}.joblib'
                    joblib.dump({'model':model,'feature_names':feature_names,'preregistration_sha256':report['preregistration_sha256'],'trained_through_exclusive':'2018-01-01','training_purged_bars':192},model_path)
            model_records.append({'model':name,'barrier_pips':pips,'diagnostics':fits})
            for config in [candidate for candidate in registration['candidates'] if candidate['model']==name and candidate['stop_pips']==pips]:
                row={'config':config}
                for split,(score,mask,first,last) in scores.items():
                    signals=mask & (score>=config['confidence_threshold'])
                    run=evaluate(arrays,signals,config,first,last,quote_kind='bid' if args.quote_side=='bid' else 'mid')
                    row[split]={'summary':run['summary'],'stability':stability(run['trades']),
                                'completed_bar_signal_count':int(signals.sum())}
                row['eligible']=passes(row,registration)
                summaries.append(row)
                a,b=[row[key]['summary'] for key in ('development','validation')]
                print(args.symbol,config['name'],'dev',a['eligible_trades'],round(a['win_rate'],4),round(a['net_profit'],2),'val',b['eligible_trades'],round(b['win_rate'],4),round(b['net_profit'],2),'eligible',row['eligible'],flush=True)
            output.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    eligible=[row for row in summaries if row['eligible']]
    ranked=sorted(eligible,key=lambda row:(-min(row['development']['summary']['net_return'],row['validation']['summary']['net_return']),-row['validation']['summary']['net_return'],row['config']['name']))
    report.update(complete=True,candidates_evaluated=len(summaries),development_validation_eligible=len(eligible),
        best_candidate=ranked[0]['config'] if ranked else None,
        interpretation='Only temporal out-of-training development and pre2022selection validation; no independent final evidence. No live or paper deployment authorized by this model report.')
    output.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    print('SAVED',output,'eligible',len(eligible),flush=True)


if __name__=='__main__':
    main()
