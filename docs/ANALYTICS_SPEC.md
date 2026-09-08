# Analytics specification

Future analytics must emit calibrated probabilities or abstain, state horizon and asset, identify
snapshot and source provenance, and separate observation time from analysis time. Evaluation must
use time-ordered holdouts, fees/slippage where relevant, regime slices, calibration error, false
discovery controls, and baseline comparisons. Accuracy alone is insufficient.

The Phase 01 `SignalEnvelope` is a storage contract, not proof of predictive value. Confidence and
impact are bounded claims from an agent; the Hub validates shape and authority but does not trust,
train, weight, or trade them.

## Future data-quality veto and routing

Before analytics, a future Data Quality Engine must assess freshness, sequence gaps, provider
conflicts, clock drift, unrealistic values, cross-exchange disagreement, and snapshot corruption.
Its veto outranks analytical confidence.

Future documented regimes are `TREND_UP`, `TREND_DOWN`, `RANGE`, `BREAKOUT`, `SQUEEZE`,
`HIGH_VOL`, `LOW_VOL`, `PANIC`, `RISK_ON`, `RISK_OFF`, `LIQUIDATION_EVENT`, `NEWS_EVENT`, `CHAOS`,
and `UNKNOWN`. Candidate strategies are trend continuation, breakout, mean reversion, liquidation
reversal, volatility squeeze, news momentum, and order-flow reversal. None is implemented.
