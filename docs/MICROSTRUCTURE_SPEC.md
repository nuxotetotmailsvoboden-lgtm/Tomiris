# Microstructure specification

Future market microstructure work must define venue, instrument, contract, timestamp source,
sequence number, book depth, trade direction method, aggregation window, gaps, and data quality.
Candidate future inputs/features are Volume-at-Price, Footprint, Bid/Ask Delta, CVD, POC,
VAH/VAL, HVN/LVN, absorption, initiative/passive classification, large trades, liquidity sweeps,
order book depth/imbalance, sequence-gap detection, executed versus displayed liquidity, spoofing
suspicion, iceberg inference, open interest, funding, and liquidations. Each feature needs leakage
tests and a provenance fingerprint.

Phase 01 supplies only the generic evidence/provenance envelope. It has no collectors, order book,
candle calculations, feature code, or market claims.
