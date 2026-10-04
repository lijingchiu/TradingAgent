"""Reproduce fixed, previously recorded candidates after the documented clock fix."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from research.intraday_mean_reversion import session_study as study
from research.intraday_sweep import fixing

ROOT=Path(__file__).resolve().parents[1]
RECEIPT=ROOT/'artifacts/intraday/execution_clock_repair_receipt.json'


def main():
    receipt=json.loads(RECEIPT.read_text())
    if receipt.get('completed'): raise RuntimeError('Repair already recorded; preserve evidence')
    original={Path(row['path']).name:row for row in receipt['original_reports']}
    early,_=study.load_verified(study.TRAIN,early=True)
    validation,_=study.load_verified(study.VALIDATE,early=False)
    observed,source=study.load_measured_book(early=True,require_complete=False)
    differences=[]
    for name in ['development_report.json','capital_500000_development_report.json',
                 'measured_book_2015_diagnostic_report.json','conservative_validation_probe_report.json']:
        item=original[name]; old=json.loads((ROOT/item['backup']).read_text()); report=deepcopy(old)
        output=[]
        for row in old['results']:
            config=study.SessionConfig(**{k:v for k,v in row['config'].items() if k!='name'})
            measured=name=='measured_book_2015_diagnostic_report.json'
            probe=name=='conservative_validation_probe_report.json'
            start,end=('2018-01-01','2022-01-01') if probe else ('2015-01-01','2016-01-01' if measured else '2018-01-01')
            frame=validation if probe else observed if measured else early
            capital=100000. if name=='development_report.json' else 500000.
            new=study.evaluate(frame,config,start=start,end=end,initial_equity=capital,
                              observed_book=measured,
                              book_source=(f"Dukascopy original paired BID/ASK M15; joint sha256={source['paired_sha256']}; complete2015 diagnostic only" if measured else None),
                              minimum_eligible_trades=1 if probe else 500)
            if probe:
                replacement=deepcopy(row)
                replacement['validation_fixed_cost_proxy_2018_2021']=study._compact(new)
                previous=row['validation_fixed_cost_proxy_2018_2021']['engine_summary']
                dev=row['development_observed_book_2015']['summary']
                replacement['pooled_natural_closes']=dev['eligible_trades']+new['summary']['eligible_trades']
                replacement['mixed_source_cost_alert_rule_passed']=bool(
                    dev['net_profit']>0 and dev['win_rate']>=.5 and
                    new['assessment']['sample_criteria_passed'] and replacement['pooled_natural_closes']>=500)
            else:
                replacement=study._compact(new)
                previous=row['engine_summary']
                if 'selection_eligible' in row:
                    replacement['selection_eligible']=bool(new['assessment']['strong_positive_expectancy_evidence'])
            differences.append(dict(report=name,candidate=config.name,
                original_count=previous['eligible_trades'],new_count=new['engine_summary']['eligible_trades'],
                original_net=previous['net_profit'],new_net=new['engine_summary']['net_profit']))
            output.append(replacement)
        report['results']=output
        report['execution_clock_repair_receipt']='artifacts/intraday/execution_clock_repair_receipt.json'
        report['script_sha256_after_execution_clock_repair']=study.digest(Path(study.__file__))
        if not probe:
            if 'eligible_count' in report: report['eligible_count']=sum(r.get('selection_eligible',False) for r in output)
            if 'best_diagnostic' in report: report['best_diagnostic']=max(output,key=lambda r:r['summary']['net_profit'])
            if 'positive_sample_count' in report: report['positive_sample_count']=sum(r['summary']['net_profit']>0 for r in output)
        else:
            report['positive_probe_candidates']=[r['config'] for r in output if r['mixed_source_cost_alert_rule_passed']]
        # No selection can be created by this repair command.
        assert report.get('selected') is None
        (ROOT/item['path']).write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
        print(name,'repaired fixed candidates',len(output),flush=True)
    fixing.run(ROOT/'data/intraday/dukascopy_eurusd_bid_development_2015_2021_m15.csv')
    receipt.update(completed=True,session_comparisons=differences,
                   session_changed_outcomes=sum(r['original_count']!=r['new_count'] or abs(r['original_net']-r['new_net'])>1e-8 for r in differences),
                   new_parameter_trials=0,final_evaluated=False)
    for item in receipt['original_reports']:
        item['repaired_sha256']=hashlib.sha256((ROOT/item['path']).read_bytes()).hexdigest()
    RECEIPT.write_text(json.dumps(receipt,indent=2,allow_nan=False)+'\n')


if __name__=='__main__': main()
