# Orchestration protocol 1.0

`AnalysisTaskRequest` is transport-neutral and forbids unknown fields. Context is bounded by depth,
item count and string size. Identity is first-class: task ID, run ID, snapshot ID, agent ID, asset
and required capability cannot be hidden in metadata.

The Orchestrator sends `POST /v1/analyze`. A valid runtime response is HTTP 202 with only task ID,
agent ID, `ACKNOWLEDGED`, acceptance time and runtime version. It means that the command was
accepted—not that analysis completed. Completion arrives later as a signed `AgentSignal` through
the Secure Hub.

Command headers are `X-Tomiris-Orchestrator-ID`, `X-Tomiris-Timestamp`, `X-Tomiris-Nonce`,
`X-Tomiris-Key-ID`, and `X-Tomiris-Signature`. HMAC-SHA256 covers, in order:

```text
METHOD
PATH
ORCHESTRATOR_ID
TARGET_AGENT_ID
TIMESTAMP
NONCE
KEY_ID
BODY_SHA256
```

Retries retain the same task ID and body but use a fresh nonce. The runtime keeps a bounded
process-local nonce TTL cache and task-idempotency cache. A Space restart may repeat handler work;
Hub uniqueness on `task_id` ensures at most one accepted final signal and therefore prevents a
duplicate downstream result.

Timeouts are independent: connection timeout, ACK timeout, cold-start grace, dispatch deadline and
signal deadline. Timeout/network reset/429/selected 5xx are retryable. Authentication, schema and
capability failures are permanent. Retry uses bounded exponential backoff plus jitter.

Task-bound signals are rejected on unknown/foreign task, run/snapshot/asset mismatch, cancelled or
failed state, duplicate result, or deadline expiry. The strict late-arrival policy is
`TASK_EXPIRED`; the rejection is audited and never becomes eligible for the run.
