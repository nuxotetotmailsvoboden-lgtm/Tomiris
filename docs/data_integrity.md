# Data integrity

`STALE DATA = INVALID FOR DECISION` is a future TOMIRIS invariant. Phase 01 enforces the parts it can: UTC-aware timestamps, bounded signal TTL, time-compatible open snapshots, raw payload hash and provenance fields.

Signals sharing `source_id` or `source_fingerprint` may have common origin. The Hub stores this fact without pretending that multiple agents are independent. Conflict evaluation, source scoring and decisions are expressly out of scope.

The transaction writes nonce, signal and accepted audit event together. Any failure rolls the transaction back. A database outage never receives an `ACCEPTED` response.

Snapshot, correlation, and causation IDs are first-class signal/audit columns. Payload JSON keeps
the full validated envelope; its SHA-256 binds it to the authenticated raw bytes. PostgreSQL
uniqueness is authoritative under concurrency and survives process restart. Outbox idempotency
prevents duplicate intent rows but external delivery remains at least once.
