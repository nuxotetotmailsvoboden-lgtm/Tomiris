# ADR 0004: Snapshot synchronization

## Context
Future analysis needs point-in-time reproducibility.
## Decision
Every signal references an existing open, non-expired snapshot.
## Consequences
Signals are tied to a known context; snapshot production is deliberately deferred.

