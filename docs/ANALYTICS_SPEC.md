# Analytics specification

Phase 03 pilot analytics emit deterministic directional strength or abstain, state horizon and
asset, identify snapshot/source/component versions, and separate observation, cutoff and processing
time. Confidence is agreement/signal strength—not a calibrated probability of profit. Calibration,
time-ordered holdouts, fees/slippage, false-discovery control and predictive evaluation remain
future requirements before any result can influence trading.

`SignalEnvelope` is a storage contract, not proof of predictive value. The Hub validates shape,
lineage and authority but does not trust, train, weight or trade analytical opinions. `NEUTRAL`
requires valid data and no edge; provider/schema/freshness/history failure produces `ABSTAIN`.

## Implemented pilot quality gate and future routing

Before pilot analytics, the Phase 03 local quality gate assesses freshness, sequence gaps,
duplicates, future/open bars, unrealistic OHLCV values and instrument identity. Its veto outranks
analytical confidence. Cross-provider consensus, clock-drift fleet monitoring and institutional
quality scoring remain future work.

Future documented regimes are `TREND_UP`, `TREND_DOWN`, `RANGE`, `BREAKOUT`, `SQUEEZE`,
`HIGH_VOL`, `LOW_VOL`, `PANIC`, `RISK_ON`, `RISK_OFF`, `LIQUIDATION_EVENT`, `NEWS_EVENT`, `CHAOS`,
and `UNKNOWN`. Candidate strategies are trend continuation, breakout, mean reversion, liquidation
reversal, volatility squeeze, news momentum, and order-flow reversal. None is implemented.
