# Deterministic feature engine

`tomiris_features` contains small, independently versioned components: `ema.v1`,
`rsi.wilder.v1`, `macd.v1`, `atr.wilder.v1`, `return.simple.v1`,
`realized-volatility.v1` and `volume-trend.v1`. `TechnicalFeaturePipeline` composes them and is
identified as `technical-pipeline.v1`.

Features accept a normalized `MarketDataSeries`; they cannot download data. Invalid or insufficient
input yields an invalid `FeatureResult`, never NaN, infinity or a fabricated zero. Tests compare
known independent values and assert RSI/ATR bounds, deterministic repetition and lookahead safety.

The shared technical engine maps EMA relation, RSI/MACD momentum, the maximum of ATR-percent and
realized-volatility regimes, returns, volume trend and a simple prior-swing breakout into visible
per-timeframe states. A documented range filter
dampens transient oscillator direction when EMA separation is small relative to ATR and no swing
breakout exists. Each evidence item names its feature and version, so future feature versions can
coexist with historical results.
