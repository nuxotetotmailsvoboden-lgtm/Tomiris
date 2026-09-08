# Threat model

## Assets and trust boundaries

Protected assets are credential secrecy, signal integrity, replay state, audit history, snapshot
identity, and notification recipient privacy. Agent HTTP input, evidence, network headers, and
Telegram are untrusted. The Hub and PostgreSQL are separate trust zones; only the Hub and worker
receive database credentials.

| Threat | Control | Residual risk |
| --- | --- | --- |
| Forged agent signal | HMAC-SHA256 over exact bytes and identity headers | Phase 01 uses a shared key |
| Replay/restart replay | timestamp window plus unique `(agent_id, nonce)` in PostgreSQL | captured request remains usable inside skew window once only |
| Concurrent replay | database uniqueness and atomic transaction | conflicting requests consume resources briefly |
| Body substitution | raw-body SHA-256 is signed and audited | compromised secret can sign new bodies |
| Resource exhaustion | Content-Length precheck plus actual streaming byte cap and schema bounds | network-level DoS needs proxy controls |
| Unauthorized agent | registry enabled/capability/asset/evidence policy | registry administration remains privileged |
| Stale context | open, unexpired, time-compatible snapshot and signal TTL | Phase 01 does not validate market truth |
| Secret disclosure | environment-only secrets, startup policy, log redaction | host compromise defeats process secrecy |
| Telegram outage/abuse | outbound-only adapter, bounded retries and dead-letter | at-least-once delivery may duplicate a message |
| Database outage | fail-closed ingestion and readiness 503 | rejection audit cannot persist while DB is down; error is logged |

There are deliberately no inbound Telegram commands or exchange credentials in this phase.
