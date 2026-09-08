# Agent authentication and key separation

Production uses HKDF-SHA256 to derive a key from master root + agent ID + key ID + purpose. The Hub
holds the `TOMIRIS_HUB_AGENT_MASTER_SECRET`; the Orchestrator holds the independent
`TOMIRIS_ORCHESTRATOR_AGENT_MASTER_SECRET`. Each Space receives only its own two derived keys.
Plaintext per-agent keys are not stored in PostgreSQL.

Purposes are fixed to `hub-ingest` and `orchestrator-command`. Domain separation means a command
key cannot authenticate Hub ingestion, and compromise of agent A does not permit impersonating
agent B. `AGENT_AUTH_MODE=shared` remains for local Phase 01 compatibility;
`AGENT_AUTH_MODE=derived` is the production recommendation.

Production endpoint policy requires HTTPS, a configured hostname suffix, no URL credentials,
query, fragment or path, and public DNS answers. Loopback/private/link-local/reserved answers are
rejected. Local TEST/DEVELOPMENT may explicitly use localhost HTTP. Endpoint records are reviewed
configuration, never values supplied by an agent response.

Signatures and all root/derived secrets are prohibited from structured logs. Rotation installs a
new key ID/root, updates Space secrets, verifies traffic, and only then removes the previous key.
