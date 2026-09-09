# Public Derivatives Data

`BinancePublicFuturesMarketDataProvider` supports Binance USDT-M public REST data only. Its model
has no API key, secret, account token, signing, balance, position, order, or execution field.

Declared capabilities currently cover futures OHLCV, REST order-book snapshot, mark price, index
price, funding rate, open interest, instrument metadata, and server time. Streaming normalization
covers trades/aggregate trades, depth deltas, mark/index/funding events, and public force-order
events.

Mark, index, and last/trade prices are separate typed contracts. Funding includes the published
rate and next funding time when supplied. Open interest records its unit and provider context;
different units must not be compared without a future normalization policy. Instrument precision,
tick size, step size, and status are obtained dynamically from exchange metadata.

Liquidation/force-order data is noisy, untrusted market-derived evidence. The normalized event
records Binance's forced-order side and provenance, but makes no claim about actor identity or why
price moved. Phase 04 contains no attribution or trade rule.

The REST adapter and WebSocket normalizer are separate components so recovery/history and live
incremental lifecycle can evolve independently.
