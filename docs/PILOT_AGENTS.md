# Phase 03 pilot agents

| Agent | Role | Asset | Capability | Meaning |
| --- | --- | --- | --- | --- |
| `BTC_CONTEXT_001` | `btc.market_context.v1` | BTCUSDT | `market.context`, `market.technical.basic` | leading-market context; BTC is not traded |
| `ETH_TECHNICAL_001` | `eth.technical.v1` | ETHUSDT | `technical.multi_timeframe` | deterministic technical observation |
| `SOL_TECHNICAL_001` | `sol.technical.v1` | SOLUSDT | `technical.multi_timeframe` | deterministic technical observation |

All defaults request closed 1d, 4h, 1h and 15m candles through declarative requirements. ETH and
SOL use exactly the same feature and technical engine code; differences live only in versioned
configuration. BTC reuses the same common features and exposes its bias as bullish, bearish or
neutral context—not permission to buy or sell BTC.

Outputs contain trend, momentum, volatility and volume state for each timeframe, overall
`LONG`/`SHORT`/`NEUTRAL`/`ABSTAIN`, bounded evidence and provenance. `NEUTRAL` means valid data with
no directional edge. `ABSTAIN` means the system could not form a reliable opinion.

Confidence v1 is deterministic strength derived from normalized signal magnitude and timeframe
agreement, bounded to 0..1 inside `AgentAnalysisResult` and converted to the legacy 0..100 signal
transport field. It is not a probability of profit, expected return or permission to trade.
