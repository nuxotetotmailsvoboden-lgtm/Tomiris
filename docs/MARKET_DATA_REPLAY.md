# Market Data Replay

Normalized events are versioned Pydantic contracts. `serialize_event()` emits canonical JSON and
`deserialize_event()` performs full schema and lineage validation. `replay_fingerprint()` sorts by
event time and event ID before SHA-256, making deterministic fixture/replay comparisons possible.

Replay must inject `DeterministicClock`, preserve canonical instrument identity and provider
provenance, keep original event/exchange/receive times, and provide an explicit snapshot cutoff.
Live and replay inputs must not be mixed within one snapshot policy without an explicit future
source-composition contract.

The Phase 04 in-memory store holds only a recent bounded window. It is intentionally cleared on
close and is not a historical archive. Future Redis/NATS/object-storage or specialized time-series
implementations may implement the store/stream interfaces. PostgreSQL remains reserved for durable
control/audit metadata and is not a tick warehouse.

Golden tests cover serialization equality, stable fingerprints, deterministic book results,
lookahead exclusion, bounded thousands-event load, and recorded/synthetic Binance wire payloads.
