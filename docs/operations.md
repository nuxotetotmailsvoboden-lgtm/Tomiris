# Operations

Start locally using the README. Stop containers with `docker compose down`; retain data with `docker compose down` and remove it only with `docker compose down -v` when explicitly intended.

Run `python -m alembic upgrade head` before application startup. Use `GET /health/live` for process liveness and `GET /health/ready` for database readiness. Read application output from the Uvicorn terminal or `docker compose logs hub`.

For secret rotation, configure new current values and old values as previous, restart Hub, deploy new agents, verify signatures, then remove previous values and restart again. Never put a secret in registry YAML, source code or git.

