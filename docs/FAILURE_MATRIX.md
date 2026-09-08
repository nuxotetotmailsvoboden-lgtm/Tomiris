# Failure matrix

| Failure | API/outbox outcome | Durable invariant | Operator action |
| --- | --- | --- | --- |
| Missing/malformed auth | 400/401 reject | no signal/nonce; rejection audit attempted | inspect reason-code counts |
| Bad signature/key/time | 401 reject | no signal/nonce | rotate/investigate if anomalous |
| Unknown/disabled agent | 403 reject | no signal/nonce | review registry |
| Schema/snapshot/TTL invalid | 422 reject | no signal/nonce | fix producer/context |
| Replayed nonce/message | 409 reject | at most one signal and nonce | investigate producer retry logic |
| Exception after nonce flush | 503 | transaction removes nonce and signal | repair dependency and retry with fresh nonce |
| PostgreSQL unavailable | readiness 503; ingestion 503 | never false `ACCEPTED` | restore DB; rejection is logged locally |
| Telegram timeout/429/5xx | `RETRY` then `DEAD_LETTER` | core records unchanged | inspect retry/dead-letter metrics |
| Telegram 4xx | `FAILED` | core records unchanged | repair token/chat/configuration |
| Worker dies while sending | stale `SENDING` lease is reclaimable | outbox remains durable | restart worker; tolerate duplicate delivery |

Every failure path is machine-coded. User-controlled validation errors must not escape as an
unhandled 500.
