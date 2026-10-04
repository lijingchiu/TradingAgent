# Intraday mean-reversion research: completed baseline families

The 112 mirror-source instrument/configuration trials and the 24 authoritative EURUSD BID replications all failed the requirement that development and validation both show positive net profit. The independent April 2022–September 2024 final sample remains untouched. No result here authorizes paper orders.

Parameters, capital and cost assumptions were fixed before each family was run. Initial paper equity was USD 100,000. Costs include two pips assumed round-trip spread, 0.2 pip slippage per side, 0.35 basis points commission per side with a USD 0.10 minimum per side, and no financed exposure or carry. Positions buy at the next observed bar open after a completed signal, with one position at a time, five calendar days maximum, conservative stop-first fills and real observed gap exits.

The following rows show the diagnostic configuration chosen by the preregistered score and sample-count rule, not a profitable selection. Net amounts are USD and include terminal sample-end liquidation; the displayed natural trade counts and net winning percentages exclude that liquidation. All configurations in these families produced negative net profit in both chronological splits, so alternative minimum-count interpretations cannot make them acceptable.

| Dataset/family | Configurations | Development trades | Development net wins | Development net USD | Validation trades | Validation net wins | Validation net USD |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| EURUSD mirror Bollinger | 24 | 2,165 | 65.40% | -840.05 | 1,382 | 64.47% | -563.64 |
| GBPUSD mirror Bollinger | 24 | 2,661 | 66.55% | -886.69 | 2,229 | 66.67% | -775.57 |
| EURUSD authoritative BID Bollinger | 24 | 1,333 | 66.09% | -513.57 | 1,391 | 64.63% | -561.47 |
| EURUSD mirror relative value | 32 | 1,198 | 66.03% | -446.18 | 965 | 64.56% | -393.68 |
| GBPUSD mirror relative value | 32 | 1,395 | 65.09% | -499.19 | 844 | 64.69% | -331.96 |

Mirror development runs through 2017 and validation spans 2018–2021; their earlier history starts in November 2012. Mirror timestamps and quote side lack source verification, so no London/New York session claim is made. Authoritative Dukascopy development spans 2015–2017 and validation spans 2018–2021 using actual UTC BID candles. The latter uses an assumed spread to model ASK entry, not a measured ASK series.

After the shared engine prevented stale Friday signals from opening after weekend gaps, all mirror configurations were rerun unchanged with an explicit 900-second age limit. Their previous reports remain beside the canonical reports as `development_report_before_explicit_age_guard.json`. The authoritative report already uses the explicit limit. Execution-integrity reruns are not counted as additional parameter hypotheses. All these canonical runs had zero reported violations of the entry-equity risk budget. This evidence does not prove an absolute peak-to-trough drawdown guarantee under all future market conditions.

A high net win percentage by itself is insufficient. A 10-pip target versus a 20-pip stop earns less per winner than a loser costs. Small fully funded positions also make minimum commissions material in pip terms. The causal signal tests pass, but the signals do not establish positive expectancy after the prescribed costs.

The separate DST-aware session study and its measured-ASK source-availability diagnostic are recorded in `session_study/`; they must not be pooled with these baseline results as an approved strategy. The complete JSON reports contain all candidates and conditional block-bootstrap diagnostics. Repeated family/source searches create selection bias; confidence intervals are not adjusted for all historical trials.
