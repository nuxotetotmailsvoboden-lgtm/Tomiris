# Market data foundation

Phase 03 implements public Binance spot market data behind `MarketDataProvider`. No API key,
account, order, position or exchange secret is accepted. Roles and features never import the
Binance client.

The normalized contracts are `OHLCVBar`, `MarketDataSeries`, `MarketDataBundle`,
`TickerSnapshot`, `MarketSummary` and `ProviderMetadata`. Raw prices and volumes use `Decimal`;
feature code performs an explicit conversion to finite `float` for numerical indicators. All
timestamps are UTC and distinguish exchange observation time, receipt time and analysis cutoff.

```text
public provider -> size/schema normalization -> closed-candle cutoff
-> monotonic/duplicate/gap/freshness validation -> feature pipeline
```

The fail-closed quality outcomes are `VALID`, `DEGRADED`, `INVALID` and `INSUFFICIENT`. Duplicate,
non-monotonic, future, open, stale, malformed, negative-volume or wrong-instrument data never
becomes `NEUTRAL`; it becomes `ABSTAIN` with a machine-readable reason.

The HTTP client enforces HTTPS and a Binance host allowlist, rejects credentials and URL suffixes,
uses TLS verification, explicit connect/read timeouts, bounded response bytes/concurrency,
non-retryable 4xx handling, bounded 429/5xx/transport retries with jitter and `Retry-After`, a
fixed User-Agent and a process-local cache. The cache is an optimization, not durable truth. Raw
candles remain transient; Phase 03 does not create a PostgreSQL candle warehouse.

The validator also requires the provider series cutoff to match the request cutoff exactly. This
prevents a seemingly valid series from being attached to the wrong replay or analytical cycle.
