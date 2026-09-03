# ADR 0005: Immutable signals and audit

## Context
Financial decisions require investigation and traceability.
## Decision
Append signals/audit events only and persist raw-payload hashes.
## Consequences
No business update/delete endpoint exists; correction requires future compensating records.

