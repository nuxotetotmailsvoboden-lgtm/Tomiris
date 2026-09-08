# Phase 02 accepted architecture decisions

Each record below is Accepted for Phase 02.

## ADR-02-01 — Universal runtime

Use one runtime plus role/config and an `AnalysisHandler` adapter. This prevents infrastructure
drift across 27 or 500 deployments.

## ADR-02-02 — Asynchronous ACK

HTTP 202 acknowledges durable work only. Results use independently authenticated Hub ingestion,
so cold starts do not require one long request.

## ADR-02-03 — Durable orchestration tasks

Runs and tasks live in PostgreSQL with immutable IDs, deadlines, attempts and audit lineage.

## ADR-02-04 — Derived per-agent credentials

HKDF-SHA256 limits the blast radius of a Space secret disclosure without storing per-agent
plaintext keys in the database.

## ADR-02-05 — Separate command and ingest roots

Orchestrator→Agent and Agent→Hub are separate security domains and cannot reuse credentials.

## ADR-02-06 — Capability routing

Registry capability and asset data selects agents. There is no fixed count or identity branch.

## ADR-02-07 — Runtime health is not registry authority

Endpoint observations live in runtime state. A handshake detects drift but cannot self-authorize.

## ADR-02-08 — Circuit breaker

Repeated operational failure opens a per-agent circuit; cooldown permits one half-open recovery.

## ADR-02-09 — PostgreSQL leasing

`FOR UPDATE SKIP LOCKED` plus expiring leases coordinates workers without a new broker.

## ADR-02-10 — Restart reconciliation

Database truth repairs interrupted dispatch/wait states while retaining task IDs and attempt data.

## ADR-02-11 — Task-bound AgentSignals

First-class task/run IDs and a unique task-result index provide authorization and at-most-one
accepted final result. Hub acceptance and task completion are one transaction.

## ADR-02-12 — Quorum is not voting

Completeness checks required capability coverage only; it never evaluates market direction.

## ADR-02-13 — No keep-alive hacks

Space sleep is a normal failure mode handled by grace, retry and deadlines. Artificial activity and
quota bypass are explicitly excluded.
