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
| Space cold start / connection reset | task enters bounded RETRY | same task ID and audit lineage | inspect ACK latency and endpoint state |
| Agent HTTP 429 / selected 5xx | exponential backoff with jitter | attempt count is durable | wait for bounded retry/cooldown |
| Agent 401/403/schema mismatch | task FAILED without blind retry | permanent reason code retained | repair secret/configuration |
| Repeated agent failure | circuit OPEN, then HALF_OPEN after cooldown | unrelated agents continue | inspect runtime state and Space logs |
| Dispatch worker crash | expired lease is reclaimed | only one active lease owner | restart worker; reconciliation resumes |
| Signal never arrives after ACK | task TIMED_OUT at signal deadline | ACK is never mistaken for completion | inspect Hub delivery from Space |
| Foreign/mismatched task result | Hub rejects and audits | no task or signal mutation | investigate compromised/misconfigured agent |
| Duplicate task result | 409 plus DB unique constraint | at most one accepted signal/task | treat repeat as idempotency event |
| Optional task loss | run DEGRADED | required capability minimum remains present | review operational quality |
| Required/critical loss | run CRITICAL + INSUFFICIENT_DATA | no optimistic completion | future decision pipeline must not start |
| Orchestrator restart | bounded DB reconciliation | no duplicate run/task creation | verify ORCHESTRATION_RECOVERED audit |
| Public provider timeout/transport error | bounded retry then `ABSTAIN/PROVIDER_*` | failure is never converted to NEUTRAL | inspect provider latency/failure metrics |
| Provider 429/selected 5xx | jittered backoff, bounded `Retry-After` | no unbounded hammering | reduce cadence or change reviewed provider endpoint |
| Provider 4xx/schema/oversized body | immediate normalized failure | no feature computation on untrusted payload | repair request/provider contract |
| Stale/future/open/duplicate/gapped bars | quality veto and `ABSTAIN` | no lookahead or invented opinion | inspect source and cutoff policy |
| Insufficient feature history | invalid feature and `ABSTAIN` | no NaN/zero substitution | fetch required closed history or adjust reviewed config |
| Role/config mismatch | fail-fast runtime startup | readiness never claims compatible analysis | repair AgentDefinition/deployment env |
| One pilot role fails | its task remains missing or returns explicit ABSTAIN | other agents and runs stay isolated | apply orchestration criticality policy |

Every failure path is machine-coded. User-controlled validation errors must not escape as an
unhandled 500.

## Phase 04 integrity paths

| Failure | System response | Recovery |
|---|---|---|
| Order-book update ID gap | book `OUT_OF_SYNC`, quality invalid | fresh REST snapshot plus compatible buffered deltas |
| Stream disconnect | close resource, `RECONNECTING`, old book unsafe | bounded reconnect followed by resync |
| Queue/buffer bound exceeded | drop/clear bounded state and fail closed | reduce load or resnapshot; never grow RAM indefinitely |
| Clock offset degraded/unsafe | degraded quality / hard snapshot veto | restore host time sync and remeasure |
| Snapshot component after cutoff | exclude from selection | wait for next explicitly cut snapshot |
| Required component missing/stale | insufficient/invalid manifest | consumer unavailable; do not dispatch analysis |
| Optional component missing | degraded manifest | proceed only where declared policy permits |
| Futures metadata mismatch | provider schema/identity error | refresh reviewed metadata and adapter |
| Private DNS answer | abort before socket connect | investigate DNS/egress; no retry to the address |
