# True-UTC local-session research: rejected on development

This family was registered before its first performance evaluation. It contains 24 fixed configurations: NY 08:00 or London 08:00 local time, with DST; unconditional or a completed, contiguous prior-six-hour decline; 2/4/6-hour holding; 40-pip stop and 20/40-pip target. Entry uses only a completed previous M15 bar and the next actual open. No clock grid was optimized.

The economic mechanism is a proposed local working-hours currency flow/reversal hypothesis. External SNB/SSRN references could not be retrieved (proxy 403), so no claim about their empirical findings is made.

Data: Dukascopy original BID M15 with authoritative UTC timestamps, 2015-01-01 through 2017-12-31 only; 74,759 actual bars. SHA-256 and provider provenance checks passed. BID is executed through the side-aware model: purchase at modeled bid plus spread and slippage; sale at bid less slippage. Spread and commission are charged once.

Both capital settings failed. The original $100,000 baseline was preserved; an additional, prospective $500,000 operational capital sensitivity used the same 24 fixed strategy configurations and unchanged fees/sizing. It was registered after observing the original baseline and before any $500,000 performance. There are 24 strategy configurations and 24 additional disclosed capital runs; these are not independent research replications.

For the best development configuration with at least 500 natural closes, NY 08:00 unconditional, six hours, stop/target 40 pips:

| Metric | $100,000 baseline | $500,000 capital sensitivity |
|---|---:|---:|
| Natural closes | 778 | 778 |
| Net winning-trade proportion | 48.7147% | 50.6427% |
| Net profit USD | -121.952320 | -49.339323 |
| Mean net P&L USD/trade | -0.156751 | -0.063418 |
| Profit factor | 0.850744 | 0.987038 |
| Inferred mid gross P&L USD | 167.556400 | 838.756820 |
| Spread/slippage USD | 133.908720 | 670.297440 |
| Explicit commissions USD | 155.600000 | 217.798703 |

All 24 baseline candidates and all 24 capital sensitivity runs had negative net profit after modeled costs. There was no eligible development winner; 2018–2021 validation was never opened by this study. Reserved final data/outcomes were never loaded. The strategy is not qualified for paper entries.

The 20-pip target variant illustrates why win rate alone is insufficient: at $100,000 it won 62.2108% of 778 natural closes but lost $156.48757 after costs, with profit factor 0.760584.

The $500,000 best result has a one-sided 95% lower bound of -9.7006297e-07 for mean UTC daily realized return (7-calendar-day circular moving-block bootstrap, 10,000 draws, seed 20261004, inactive days retained). This conditional development estimate is not corrected for candidate or capital selection. There is no positive expectancy evidence.

Risk: no observed breach in these studies. The entire funded principal remains capped at 0.8% of equity, with modeled worst-case principal plus liquidation costs below 1%. Both adverse excursion and open-position peak-to-trough drawdown were measured. No margin, short selling, or real broker order is used.

Five synthetic checks cover local DST clock mapping, feature warmup, missing-bar continuity, and causal invariance to future price edits. They are implementation checks, not performance evidence.

An appended execution clarification makes max_signal_age_seconds=900 explicit. The original run already inferred this same bound and also rejected noncontiguous entry bars. A fixed $100,000 rerun of the leading 778-trade configuration reproduced the original summary and bootstrap exactly; the original receipts were not overwritten.

Receipts: preregistration.json, development_report.json, capital_500000_preregistration.json, capital_500000_development_report.json, execution_clarification_receipt.json, synthetic_checks.json.

## Appended authentic-book confirmation: source coverage blocked

After the fixed-spread failures, an observed BID/ASK source-confirmation round was separately registered before any of its strategy P&L. It retains exactly the same 24 clock/price/holding configurations, the $500,000 capital sensitivity, original commissions and 0.2-pip each-side slippage. Purchases use the original aligned ASK open; liquidations use BID minus slippage. BID reference gross profit is reported separately from observed spread, slippage and commission. Invalid or unavailable ASK opens block new entries; they never remove valid BID exit bars or supply invented executable quotes.

The full required ASK source is unavailable because the upstream returned sustained HTTP503: only2015 has complete archive coverage, 2016 has77 archives, 2017 has2 sample days and 2018–2021 has only4 sample days. The paired early data retains all74,759 BID observations but only31,065 valid ASK opens. The canonical development and validation loader refuses incomplete archive coverage before strategy P&L. No canonical observed-book selection or final evaluation has occurred.

A further source-availability appendix was registered BEFORE any actual-book P&L, restricting an EXPLORATORY diagnostic to source-complete2015. All24 fixed configurations were evaluated; five produced positive sample net profit. These do not qualify a strategy.

The best2015 diagnostic was NY08 unconditional, six hours, 40-pip stop/target:259 natural closes,51.3514% net wins, net+$155.848343, profit factor1.105083. Its BID gross profit+$290.025410 reconciles actual spread$24.270250, slippage$37.374080 and commissions$72.532737. The7-calendar-day bootstrap one-sided95% lower mean daily-return bound is−9.76391475e−7: estimated expectancy remains uncertain. No observed1% risk violation occurred. The259 closes fall below500, and validation is unavailable. This is a selected development diagnostic, not independent final evidence.

Twelve synthetic implementation checks pass, covering clock/DST/causality plus actual ASK fills, unavailable ASK blocking, preservation of BID exits and cost reconciliation. The live coverage checks confirm incomplete sources are blocked.

Additional receipts: measured_book_preregistration.json, measured_book_synthetic_checks.json, measured_book_2015_diagnostic_preregistration.json, measured_book_2015_diagnostic_source_receipt.json, measured_book_2015_diagnostic_report.json, measured_book_coverage_block_receipt.json. Previous negative machine-readable receipts remain unchanged. The cumulative session effort is24 strategy configurations,24 extra capital runs and24 extra source-complete2015 diagnostics. The planned48 full-source split runs have NOT occurred.

When full authoritative side files become available, the saved commands are `python -m research.intraday_mean_reversion.session_study book-train` and `book-validate`, with the existing analysis dependencies on PYTHONPATH. These verify original side/paired hashes, reject incomplete sources, evaluate the unchanged family, report both split counts and retain the final/paper gates closed. The final interval is never opened by this module.

## Appended conservative selection-validation probe: all five failed

Before its outcomes, a separate preregistration declared only the five configurations with positive net sample profit in the complete2015 observed-book diagnostic. Each unchanged configuration was tested on full authoritative UTC BID2018–2021, using the original2-pip fixed-spread assumption,0.2-pip each-side slippage and unchanged commissions at$500,000. This is a conservative cost proxy, NOT a claim that2018–2021 historical ASK exists. Source/cost conventions differ from the2015 development diagnostic and are explicitly retained in every result.

All five validation probes failed both net profitability and the50% net-win threshold. The least negative was NY08 prior-six-hour decline, six hours,40/40:552 natural closes,46.7391% wins,−$431.144730,profit factor0.826795; pooled with its139 development closes gives691, not independent final evidence. The leading2015 diagnostic (NY08 unconditional,six hours,40/40) had1,038 validation closes,45.0867% wins,−$1,093.787105,profit factor0.764486; pooled259+1,038=1,297. All five had zero observed1% breaches and negative7-day bootstrap lower bounds. No parameters were retuned, no winner was selected, and no final test or paper entry was enabled.

A loader defect was repaired before any probe P&L: the full source provenance omitted its optionalquality field. Checksums/UTC/BID verification remain required, and local OHLC/duplicate/boundary checks provide the missing quality observation. The original preregistration was preserved; the separate repair receipt states the exact failure and correction.

Probe receipts: conservative_validation_probe_preregistration.json, conservative_validation_probe_source_receipt.json, conservative_validation_probe_loader_repair_receipt.json, conservative_validation_probe_report.json. Session research now totals24 strategy configurations,24 additional capital runs,24 complete2015 observed-book diagnostics and5 conservative validation probes =77 disclosed runs. The full canonical observed-book confirmation remains blocked by missing2016–2021ASK archives. Twelve current synthetic checks pass, including crossed ASK entry blocking and valid BID liquidation after ASK disappears.
