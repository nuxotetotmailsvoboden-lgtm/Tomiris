# Agent task lifecycle

```mermaid
stateDiagram-v2
  [*] --> PENDING
  PENDING --> DISPATCHING: PostgreSQL lease
  RETRY --> DISPATCHING: lease after backoff
  DISPATCHING --> WAITING_SIGNAL: valid 202 ACK
  DISPATCHING --> RETRY: retryable failure
  DISPATCHING --> FAILED: permanent/bounded failure
  WAITING_SIGNAL --> SIGNAL_RECEIVED: Hub transaction
  WAITING_SIGNAL --> TIMED_OUT: signal deadline
  DISPATCHING --> RETRY: expired worker lease
  PENDING --> CANCELLED: run terminal/cancelled
  SIGNAL_RECEIVED --> [*]
  FAILED --> [*]
  TIMED_OUT --> [*]
  CANCELLED --> [*]
  SKIPPED --> [*]
```

One task is exactly one agent + one asset + one snapshot + one capability. A task ID is stable
across dispatch attempts. ABSTAIN is a valid final result and completes a task. HTTP ACK does not.

FULL requires every planned task result and no planning gap. DEGRADED requires every required
capability minimum but permits optional/non-critical loss. CRITICAL with `INSUFFICIENT_DATA` means
a required minimum or explicitly critical assignment cannot be met. This is collection quorum,
not majority voting over analytical opinions.
