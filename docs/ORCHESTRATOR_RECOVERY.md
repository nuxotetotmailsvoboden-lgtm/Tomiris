# Orchestrator recovery

On startup a bounded PostgreSQL reconciliation pass finds unfinished runs and their tasks. It
reclaims expired DISPATCHING leases, preserves active leases, expires missed signal deadlines, and
reconciles a task when its signal already exists. It never creates a replacement run or changes a
task ID.

```mermaid
flowchart TD
  S[Worker starts] --> R[Read unfinished runs]
  R --> L{Expired DISPATCHING lease?}
  L -->|yes, dispatch deadline open| B[RETRY same task ID]
  L -->|yes, deadline closed| T[TIMED_OUT]
  L -->|no| W{WAITING_SIGNAL expired?}
  W -->|yes| T
  W -->|no| D{Signal already stored?}
  D -->|yes| C[SIGNAL_RECEIVED]
  D -->|no| K[Keep durable state]
  B --> Q[Re-evaluate completeness]
  T --> Q
  C --> Q
  K --> Q
```

`ORCHESTRATION_RECOVERED` records a material repair. Polling is bounded and configurable, using
indexed task/run status, dispatch time and lease columns. This Phase intentionally avoids another
state system such as Redis or Kafka.
