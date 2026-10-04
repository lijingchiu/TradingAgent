"""Persist the bounded model family before examining candidate outcomes."""
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path

from trading_agent.risk import DEFAULT_COSTS

ROOT = Path(__file__).resolve().parents[2]


def main():
    path = ROOT / 'artifacts/intraday/model/preregistration.json'
    if path.exists():
        print('Existing preregistration preserved:', path)
        return
    candidates = [
        {'name': f'{model}_b{pips}_h{horizon}_p{threshold:.2f}',
         'model': model, 'stop_pips': pips, 'target_pips': pips,
         'horizon_bars': horizon, 'confidence_threshold': threshold}
        for model in ('hist_gradient_boosting', 'random_forest')
        for pips, horizon in ((20, 96), (30, 192))
        for threshold in (.55, .60, .65)
    ]
    record = {
        'registered_at_utc': datetime.now(timezone.utc).isoformat(),
        'family': 'cost_aware_long_intraday_classifier', 'timeframe': 'M15',
        'models': {
            'hist_gradient_boosting': {'max_iter': 100, 'learning_rate': .05,
                'max_leaf_nodes': 7, 'max_depth': 3, 'min_samples_leaf': 256,
                'l2_regularization': 10, 'max_bins': 128, 'early_stopping': False,
                'random_state': 20261004},
            'random_forest': {'n_estimators': 96, 'max_depth': 6,
                'min_samples_leaf': 256, 'max_features': .7, 'n_jobs': 2,
                'random_state': 20261004},
        },
        'candidates': candidates, 'candidate_count_per_symbol_source': len(candidates),
        'training_development_model': ['2015-01-01', '2017-01-01'],
        'out_of_training_development': ['2017-01-01', '2018-01-01'],
        'refit_training_validation_model': ['2015-01-01', '2018-01-01'],
        'selection_validation': ['2018-01-01', '2022-01-01'],
        'reserved_final_not_evaluated': ['2022-04-01', '2024-10-01'],
        'purge_embargo_bars': 192,
        'feature_warmup_bars': 192,
        'features': ['completed_log_return_lags_1_2_4_8_16_32_64_96',
                     'lagged_1bar_returns_1_2_3', 'rolling_volatility_8_32_96',
                     'rolling_return_mean_8_32_96', 'close_zscore_20_96',
                     'atr_14_96_pips', 'atr_ratio_14_to_96',
                     'normalized_return_by_atr_4_16_64', 'candle_body_by_range',
                     'close_location_in_bar', 'range_ratio_to_atr',
                     'range_position_96', 'ema_distance_20_96_by_atr'],
        'forbidden_features': ['source_clock_hour', 'weekday', 'session',
                               'future_prices', 'current_next_bar_open'],
        'label': 'Positive net next-open first-hit/timeout liquidation after fixed modeled spread, slippage and actual minimum commissions; stop wins unknown intrabar ordering',
        'labels_cost_aware': True,
        'initial_equity': 100000, 'cost_model': asdict(DEFAULT_COSTS),
        'position_policy': 'long only; one fully funded conversion; principal <=0.8% equity; worst funded loss <=1%; maximum5calendar days; next-open entry',
        'sampling_training': 'Every fourth eligible training bar, deterministic index modulo4, reducing overlapping labels without choosing outcomes',
        'development_validation_gap': 'Purge the last192training observations; skip first192evaluation observations. Labels within each training interval only; no future final labels.',
        'selection_eligibility': {'development_net_profit_gt': 0, 'validation_net_profit_gt': 0,
            'development_win_rate_gte': .50, 'validation_win_rate_gte': .50,
            'development_natural_trades_gte': 200, 'validation_natural_trades_gte': 1000,
            'risk_breaches': 0, 'observed_trade_peak_drawdown_lte': .01},
        'selection_ranking': 'max min(development net_return,validation net_return), then validation net_return descending, then stable candidate name ascending',
        'baselines': ['always_long_same_barriers', 'completed16bar_momentum_above_zero_same_barriers'],
        'stability': 'Report calendar daily and monthly net PnL; no post hoc selection of favorable months',
        'final_permission': 'Runner rejects evaluation after2021Dec31; root must freeze one winner before any final test',
        'uncertainties': ['Training labels overlap; temporal purging reduces but does not eliminate dependence',
            'Mirror price side/broker/timezone unknown; no clock features, provisional research only',
            'Predicted profitability confidence is not a calibrated probability guarantee',
            'Model is not deployed; shared paper-model implementation needed for same-logic execution'],
    }
    path.write_text(json.dumps(record, indent=2)+'\n')
    print(path)


if __name__ == '__main__':
    main()
