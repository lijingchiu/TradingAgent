"""Bounded USD/JPY study, with JPY account units explicitly declared."""
from datetime import datetime,timezone
import json
from pathlib import Path
from dataclasses import asdict
from trading_agent.risk import CostModel

ROOT=Path(__file__).resolve().parents[2]
FOLDER=ROOT/'artifacts/intraday/jpy'
SOURCE='https://raw.githubusercontent.com/ejtraderLabs/historical-data/fbd29b3cd85c0eea4f6e8b81c053f98fb3de22fd/USDJPY/USDJPYm15.csv'
COSTS=CostModel(spread_pips=2,slippage_pips=.2,commission_bps=.35,minimum_commission=10,pip_size=.01)


def main():
 path=FOLDER/'preregistration.json'
 if path.exists():
  print('Existing preregistration preserved',path);return
 candidates=[{'name':f'usdjpy_ema384_1536_dip{dip}_rebound{rebound}_target{target}_stop{stop}',
  'ema_fast':384,'ema_slow':1536,'ema_slow_slope_bars':96,'rsi_period':2,
  'dip_threshold':dip,'rebound_threshold':rebound,'armed_expiry_bars':24,
  'target_pips':target,'stop_pips':stop,'max_holding_bars':96 if stop==50 else 192,
  'max_holding_days':5,'warmup_bars':4608}
  for target in (20,30,50) for stop in (50,80) for dip in (5,10) for rebound in (20,30)]
 record={'registered_at_utc':datetime.now(timezone.utc).isoformat(),'symbol':'USDJPY','timeframe':'M15',
  'family':'same_predeclared_bull_regime_deep_dip_rebound_on_different_fx_asset',
  'source_url':SOURCE,'source_pinned_commit':'fbd29b3cd85c0eea4f6e8b81c053f98fb3de22fd',
  'source_price_side':'UNKNOWN; scenario assumes indicative mid OHLC','source_timezone':'UNKNOWN; no session or clock predictors',
  'price_divisor':1000,'pip_size_quote_currency':.01,'quote_currency':'JPY','base_currency':'USD',
  'account_currency':'JPY','initial_equity':50000000,
  'account_explanation':'JPY50m paper cash pays in full for USD units. At entry, USDunits*JPYperUSD<=0.8% of JPY equity; complete JPY principal plus worst-case fees<=1% of entry JPY equity. PnL and commissions are JPY, not USD. JPY50m~USD350k is only rough explanatory conversion, no fixed exchange assumption for account valuation.',
  'cost_model':asdict(COSTS),'candidate_count':24,'candidates':candidates,
  'development':['2015-01-01','2018-01-01'],'selection_validation':['2018-01-01','2022-01-01'],
  'final_evaluated':False,'final_permission':'None; no2022+ candidate outcomes may be inspected',
  'entry':'Completed RSI2 rebound after prior deep dip within24bars, EMA384>EMA1536 and EMA1536>lag96; next M15 open within900s only; no same-bar reopen.',
  'holding_hours_by_stop':{'50':24,'80':48},'principal_exposure_fraction':.008,'entry_equity_loss_cap':.01,
  'observed_trade_peak_drawdown_cap':.01,
  'selection_eligibility':'Both splits netprofit>0, natural netwins>=50%, no entry loss/peakdrawdown breaches, development+validation natural closes>=500. Final500naturalcloses remains distinct and unevaluated.',
  'selection_rank':'Max min(development netreturn,validation netreturn), then validation netreturn, then stable name',
  'untuned_baselines':6,'baseline_rule':'Always long with the same6stop/target/holding variants, not selection candidates',
  'limitations':['Broker mirror timestamps and executable quote side are unknown; ordering only, no UTC session assumption.',
   'Currency scaling inferred from1000JPYquote points per yen and validated plausible2015–2021 prices; original broker metadata is unavailable.',
   'No final test or broker paper execution follows from mirror success; independent authentic USDJPY data required.']}
 path.write_text(json.dumps(record,indent=2)+'\n');print(path)


if __name__=='__main__':main()
