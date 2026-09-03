# Architecture

The Hub is the sole ingress boundary between future agents and PostgreSQL. Agents never receive database credentials: they send authenticated envelopes to `/v1/signals`; the Hub authenticates, validates, persists and audits them atomically.

A snapshot gives every future analyst a shared point-in-time context. Phase 01 does not build market data: the internal test script creates snapshots only for protocol validation.

The Hub is agent-count agnostic. Registry rows, not hard-coded conditionals, define enabled agents. Phase 01 intentionally has no voting, learning, trading decision, market calculation or exchange integration.

