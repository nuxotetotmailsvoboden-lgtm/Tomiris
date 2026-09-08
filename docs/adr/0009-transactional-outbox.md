# ADR 0009: transactional notification outbox

Status: accepted.

Persist notification intent in PostgreSQL before external delivery. A unique idempotency key and
explicit state machine make failures visible; `SKIP LOCKED` permits multiple workers. Direct
Telegram calls from core transactions are rejected because external latency/failure would couple
messaging to durable Hub state.
