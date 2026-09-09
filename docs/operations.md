# Operations

Start locally using the README. Stop containers with `docker compose down`; retain data with `docker compose down` and remove it only with `docker compose down -v` when explicitly intended.

Run `python -m alembic upgrade head` before application startup. Use `GET /health/live` for process liveness and `GET /health/ready` for database readiness. Read application output from the Uvicorn terminal or `docker compose logs hub`.

Queue the only Phase 01 notification with `python scripts/create_system_test_notification.py`,
then process one row with `python scripts/run_notification_worker.py`. With
`TELEGRAM_ENABLED=false` (default), the worker uses Console. Telegram requires both environment
values and is outbound-only. Alert on readiness 503, rejection-audit write failures, `FAILED`,
stale `SENDING`, and `DEAD_LETTER` rows.

For secret rotation, configure new current values and old values as previous, restart Hub, deploy new agents, verify signatures, then remove previous values and restart again. Never put a secret in registry YAML, source code or git.

## Phase 02 operations

Apply migration 0003 before enabling a worker. Configure different random values for
`TOMIRIS_HUB_AGENT_MASTER_SECRET` and `TOMIRIS_ORCHESTRATOR_AGENT_MASTER_SECRET`; production should
use `AGENT_AUTH_MODE=derived`. Derive and install only the two agent-specific keys in each Space
with `scripts/derive_agent_secret.py`.

Register each logical agent, then its HTTPS endpoint. Validate `/health/live`, `/health/ready` and
`/v1/capabilities`; health is advisory and does not replace a real task outcome. Start with TEST
agents and run:

```powershell
python scripts/run_test_orchestration.py --asset TEST --capability test.echo --agents 3
```

The command prints compact JSON and never emits a trading signal. Alert on CRITICAL runs,
`AGENT_AUTH_FAILED`, endpoint policy rejection, repeated timeouts, circuit open, expired leases and
recovery events. Do not notify Telegram for every retry or probe. Space sleep needs no keep-alive;
the cold-start grace, retry policy and signal deadline are the supported controls.

Production HF deployments must install TOMIRIS from an owner-approved immutable tag. Existing
Phase 02 deployments may remain pinned to `v0.2-orchestrator-pass`; never replace a certified pin
with `main` or a feature branch. Upgrade or rollback a specific Space by selecting the appropriate
compatible certified tag and rebuilding it.

## Phase 03 pilot operations

Apply migration 0004 and sync the reviewed registry. For an analytical Space set
`TOMIRIS_RUNTIME_MODE=analytical`, a single `TOMIRIS_AGENT_DEFINITION_PATH`, matching identity,
role/capabilities/assets, and the existing two purpose-separated secrets. The selected definition
must be one of `agents/definitions/*.yaml`; never place provider or exchange secrets in it.

Run an explicit public-data preview without accounts or orders:

```powershell
python scripts/run_live_pilot_analysis.py
```

The command fetches only public closed candles and prints analytical biases plus version lineage.
It does not submit orders or claim profitability. Deterministic CI uses fixtures; public-provider
availability is never a required CI dependency. Monitor market-data request/failure/latency,
analysis failure/abstention/latency and feature failure counters without task UUID labels.

The Phase 03 template is pinned to `v0.3-pilot-agents-pass`. The owner creates that tag after final
review; pre-release CI validates local source without fetching it. BTC/ETH/SOL analytical Spaces
require this tag or a later compatible certified release. Rebuild and verify the capability/role
API handshake one Space at a time—simultaneous fleet rollout is unnecessary. Roll back an affected
Space by restoring its previous certified tag. Do not point a Space at `main` or a feature branch.

## Phase 04 market-data operations

Deterministic CI never calls Binance. To perform an explicit public-data smoke from an approved
network:

```powershell
python scripts/run_market_data_smoke.py
```

The command reads spot/futures public data for BTC/ETH/SOL, measures clock offset, bootstraps books,
builds a verified manifest, and always reports `trade_execution: DISABLED`. It accepts no API key.

Monitor `market_stream_connections`, `market_stream_reconnects`, `market_stream_failures`,
`market_stream_events_total`, `market_stream_dropped_total`, `market_sequence_gaps_total`,
`market_resync_total`, `market_snapshot_build_total`, `market_snapshot_failure_total`,
`market_quality_invalid_total`, `market_clock_drift_ms`, and `market_data_age_seconds`. Investigate
unsafe drift and repeated resync immediately. Do not use self-ping, account rotation, or traffic to
bypass provider quotas.

Phase 04 intentionally adds no migration: recent events are transient/bounded, and existing
snapshot metadata can retain compact fingerprint/quality references. PostgreSQL must not become a
tick warehouse. Production should combine application DNS validation with outbound firewall rules.

During development, HF Spaces remain pinned to `v0.3-pilot-agents-pass`. Do not create or deploy a
`v0.4-market-data-plane-pass` tag until owner review and separate release certification.
