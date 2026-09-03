# ADR 0006: Fail closed

## Context
Ambiguous security or persistence outcomes are unsafe.
## Decision
Reject invalid, stale, duplicate, unknown and unavailable-database requests.
## Consequences
Availability can reduce during dependency failures, but Hub never falsely acknowledges storage.

