# Security

Every request uses HMAC-SHA256 over method, path, authenticated agent ID, epoch timestamp, nonce, key ID and SHA256 of exact raw body bytes. Comparison is constant-time. The Hub checks clock skew, key ID, agent status, payload/header identity and protocol version.

PostgreSQL uniqueness on `(agent_id, nonce)` blocks replay even after restart. `message_id` blocks a second business signal. Both are deliberately distinct. Accepted signals and audit rows are append-only; business endpoints have no update/delete operation.

Phase 01 uses one shared secret to allow initial deployment. A compromise of any agent credential requires immediate rotation: set a new current key/secret, retain the old pair only temporarily as previous, redeploy agents, then remove previous credentials. Future per-agent credentials are not implemented.

External evidence is untrusted data, never an instruction. Request body size and evidence-schema limits bound resource use. In production, empty, short and known placeholder secrets prevent startup.

The request reader checks declared length early and independently counts streamed bytes; a false
or absent `Content-Length` cannot bypass the limit. Malformed identity, key, nonce, timestamp, and
signature inputs return controlled reason codes. If rejection auditing cannot reach PostgreSQL,
ingestion stays rejected and the audit-write failure is emitted to operational logs.

Production policy is deliberately practical rather than an entropy proof: use a password manager
or CSPRNG to generate a unique secret. Known example/development values, placeholder markers, and
single-character repetition are blocked. The `.env.example` secret is empty by design and cannot
start the service until explicitly supplied.
