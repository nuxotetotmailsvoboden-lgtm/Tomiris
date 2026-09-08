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
| Forged orchestration command | target-bound HMAC, time window and nonce cache | process-local nonce history is lost on Space restart |
| One Space secret disclosed | HKDF-derived per-agent/purpose key | compromised Space can submit only its own result until rotation |
| Command key used for ingest | independent roots and HKDF purpose separation | root-host compromise defeats domain isolation |
| Agent endpoint SSRF | reviewed endpoint table, HTTPS/host allowlist, URL and DNS checks | DNS can change after validation; egress firewall remains recommended |
| Runtime capability escalation | registry remains authority; handshake only detects drift | registry administration remains privileged |
| Duplicate work after restart | stable task ID and unique accepted result | handler computation may repeat but cannot create a second accepted result |
| Late result | Hub rejects `TASK_EXPIRED` and audits rejection | rejection audit lacks accepted signal payload by design |
| Malformed public market data | strict JSON/OHLCV normalization, byte limits and quality gate | one provider can still publish plausible but incorrect prices |
| Provider endpoint abuse/SSRF | HTTPS, credential-free origin and Binance host allowlist | DNS/CA/host compromise needs network egress controls |
| Lookahead/open-candle contamination | explicit UTC cutoff and closed-candle validation | provider timestamp semantics require continued monitoring |
| Cross-asset contamination | definition, task, request, bundle and role identity checks | bad reviewed configuration can still disable an agent |
| Analytical code injection via remote text | Phase 03 accepts numeric schema only; no LLM/instruction execution | future text agents need stronger content isolation |
| Misread confidence as profit probability | versioned deterministic-strength semantics and documentation | downstream consumers must preserve the distinction |

There are deliberately no inbound Telegram commands, exchange credentials, private/account market
sources, trading decisions or execution functions in this phase.
