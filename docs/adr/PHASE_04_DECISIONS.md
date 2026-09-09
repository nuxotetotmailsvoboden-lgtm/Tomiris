# Phase 04 architecture decisions

Status: accepted for owner review; no release tag created.

1. **Canonical identity.** Venue, market type, symbol, assets, and contract type are first-class;
   spot and futures symbols never collapse into one key.
2. **Additive Phase 03 bridge.** Existing OHLCV requests and pilot roles remain intact. Adapters
   wrap closed Phase 03 series into normalized events.
3. **Capabilities over provider conditionals.** A registry routes declared market/data types.
4. **REST bootstrap, streaming incrementals.** Their resources and failure lifecycles are separate.
5. **Provider-neutral events.** Raw Binance JSON is validated at one adapter boundary.
6. **Five temporal meanings.** Event, exchange, receive, process, and snapshot-cutoff time are not
   interchangeable. All are UTC.
7. **Measured clock drift.** Offset is observed, never corrected by the application; unsafe drift
   vetoes snapshot eligibility.
8. **Snapshot plus delta synchronization.** Depth is usable only after a bridging sequence.
9. **Sequence gaps fail closed.** Gaps never become a neutral analytical observation.
10. **Bounded memory/backpressure.** Event queues/stores and recovery buffers have count/byte/time
    limits. Overflow requires recovery.
11. **No PostgreSQL tick warehouse.** No migration 0005 is justified in this phase. Existing
    `market_snapshots.metadata_json` can carry the compact manifest fingerprint/quality reference.
12. **Verified manifest.** Canonical SHA-256, provenance, component ranges, quality, and cutoff make
    a snapshot auditable and replayable.
13. **No lookahead.** Events after `as_of` and open candles are excluded.
14. **Public derivatives only.** There is deliberately no exchange credential or private endpoint.
15. **SSRF/DNS defense.** TLS, host/path allowlists, credential-free URLs, no redirects, and global
    DNS results are mandatory; local override is explicit.
16. **Independent rollout.** HF deployment remains pinned to `v0.3-pilot-agents-pass` until owner
    certification creates a later release. Phase 04 does not tag or merge itself.
