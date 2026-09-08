# Operations

Start locally using the README. Stop containers with `docker compose down`; retain data with `docker compose down` and remove it only with `docker compose down -v` when explicitly intended.

Run `python -m alembic upgrade head` before application startup. Use `GET /health/live` for process liveness and `GET /health/ready` for database readiness. Read application output from the Uvicorn terminal or `docker compose logs hub`.

Queue the only Phase 01 notification with `python scripts/create_system_test_notification.py`,
then process one row with `python scripts/run_notification_worker.py`. With
`TELEGRAM_ENABLED=false` (default), the worker uses Console. Telegram requires both environment
values and is outbound-only. Alert on readiness 503, rejection-audit write failures, `FAILED`,
stale `SENDING`, and `DEAD_LETTER` rows.

For secret rotation, configure new current values and old values as previous, restart Hub, deploy new agents, verify signatures, then remove previous values and restart again. Never put a secret in registry YAML, source code or git.
