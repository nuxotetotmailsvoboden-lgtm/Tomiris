# ADR 0002: HMAC ingestion authentication

## Context
Agents must authenticate without database access.
## Decision
Authenticate raw HTTP requests with HMAC-SHA256 plus timestamps/nonces.
## Consequences
Requests are integrity-protected and replay-resistant; secret protection is operationally critical.

