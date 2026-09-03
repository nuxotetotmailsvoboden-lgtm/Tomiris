Phase 01 concurrency acceptance requires at least ten simultaneously signed requests sharing one `(agent_id, nonce)` against real PostgreSQL. The expected result is one `202` and only controlled replay conflicts.

