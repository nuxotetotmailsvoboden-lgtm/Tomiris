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
