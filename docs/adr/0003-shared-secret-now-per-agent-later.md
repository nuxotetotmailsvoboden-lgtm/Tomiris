# ADR 0003: Shared secret now, per-agent later

## Context
Phase 01 needs a simple bootstrap credential.
## Decision
Use a SecretProvider abstraction with a shared-secret implementation and key IDs.
## Consequences
A compromise requires global rotation; endpoint/protocol do not need redesign for future per-agent secrets.

