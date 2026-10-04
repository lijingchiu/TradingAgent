"""An economically distinct bounded pullback family, before any family P&L."""
from dataclasses import asdict
from datetime import datetime,timezone
import json
from pathlib import Path
from trading_agent.risk import DEFAULT_COSTS

ROOT=Path(__file__).resolve().parents[2]
PATH=ROOT/'artifacts/intraday/model/pullback_preregistration.json'


def main():
    if PATH.exists():
        print('Existing pullback preregistration preserved:',PATH)
        return
    candidates=[{'name':f'ema384_1536_dip{dip}_rebound{rebound}_target{target}_stop{stop}',
        'ema_fast':384,'ema_slow':1536,'ema_slow_slope_bars':96,'rsi_period':2,
        'dip_threshold':dip,'rebound_threshold':rebound,'armed_expiry_bars':24,
        'target_pips':target,'stop_pips':stop,'max_holding_bars':96 if stop==50 else 192,
        'max_holding_days':5,'warmup_bars':4608}
        for target in (20,30,50) for stop in (50,80)
        for dip in (5,10) for rebound in (20,30)]
    registration={'registered_at_utc':datetime.now(timezone.utc).isoformat(),
        'family':'bull_regime_deep_dip_completed_rebound','symbol':'EURUSD','timeframe':'M15',
        'hypothesis':'Buy a completed rebound from deep short-term oversold readings only in a multi-day bullish price regime. The rebound condition reduces buying during a still-falling dip; wide stops accommodate intraday noise. This is distinct from the classifier family.',
        'candidates':candidates,'candidate_count':24,
        'source_file':'data/intraday/dukascopy_eurusd_bid_development_2015_2021_m15.csv',
        'source_price_side':'BID','quote_kind':'bid','timezone':'UTC',
        'development':['2015-01-01','2018-01-01'],
        'selection_validation':['2018-01-01','2022-01-01'],
        'reserved_final_not_evaluated':['2022-04-01','2024-10-01'],
        'cost_model':asdict(DEFAULT_COSTS),'capital_scenarios':[100000,500000],
        'capital_note':'The $500k scenario is predeclared operating-capital sensitivity: principal cap becomes$4000; percentage commission exceeds the$0.10minimum at notional>$2857.14. This changes cost drag and is a separate disclosed operating choice, not leverage.',
        'decision_rule':'EMA384>EMA1536 and EMA1536>its completed value96barsago; arm when RSI2<=dip; buy only a subsequent completed upward RSI cross of rebound within24bars while bullish regime remains true; reset arm on regime loss or expiry.',
        'execution':'Next fresh M15 open only(max signal age900s); one fully funded long; stop-first; opening gaps use actual observed open; no same-bar reopen; stop/target distances fixed from actual next-open entry.',
        'risk_limits':{'funded_principal_fraction':.008,'maximum_entry_loss_fraction':.01,'maximum_observed_trade_peak_drawdown_fraction':.01},
        'holding_hours_by_stop':{'50':24,'80':48},
        'selection_eligibility':'Positive after-cost net P&L, winrate>=50%, no entry-loss or observed peak-drawdown breaches in both development and validation; development+validation natural closes>=500. Final500natural closes remains a distinct preferred evidence target, never implied by pooled count.',
        'selection_ranking':'Maximum minimum(development net_return,validation net_return); then validation net_return; then smaller capital; then stable name. Capital choice must be frozen with selected strategy.',
        'baselines':'Always-long fixed stop/target/holding for the same6barrier configurations at each of2capitals;12untuned additional control configurations, not eligible for model selection.',
        'stability':'Report yearly/monthly/daily P&L with fixed parameters; no post hoc favorable months or session selection.',
        'final_cost_stress_if_frozen':[1.5,2.0],
        'candidate_count_with_capital_scenarios':48,
        'limitations':['Selection validation has been seen in prior research; final outcomes remain unopened.',
            'BID history plus assumed constant spread is a modeled execution scenario, not measured ASK liquidity.',
            'Frequent winner counts can hide larger losses; net payoff and expectancy decomposition remain required.']}
    PATH.write_text(json.dumps(registration,indent=2)+'\n')
    print(PATH)


if __name__=='__main__':main()
