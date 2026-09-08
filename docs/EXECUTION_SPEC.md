# Execution specification

Execution is forbidden in Phase 01. A future subsystem must be isolated from analytics and require
a signed decision plus deterministic risk approval. It must specify venue idempotency keys, order
state reconciliation, partial fills, timeouts, retries, rate limits, clock sync, position truth,
reduce-only behavior, precision/minimums, fees, slippage, and a fail-closed kill switch.

Exchange credentials must never enter the Hub agent contract, notification payload, logs, or
Telegram adapter. No Binance, Bybit, MT5, or Exness code exists here.

A future venue specification must explicitly model Mark Price, Index Price, Last Price,
`workingType`, `priceProtect`, tick size, step size, minimum quantity/notional, dynamic leverage
brackets, maintenance margin, ADL, funding, fees, spread, slippage, partial fills, `reduceOnly`,
`closePosition`, one-way/hedge mode, isolated/cross margin, client order ID, and reconciliation.
