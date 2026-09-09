# TOMIRIS — Phase 04 Market Data Plane

Phase 04 adds canonical spot/futures identity, public derivatives contracts, normalized streaming,
temporal and sequence integrity, bounded event handling, and verified market snapshots to the
secure Hub, durable Orchestrator, and Phase 03 pilot roles. The three pilots remain BTC market
context, ETH technical and SOL technical. They produce observations only: an `AgentSignal` is never
a trade decision, order, position, leverage, stop or take-profit instruction.

## Windows quick start

1. Install Python 3.12+, Git and Docker Desktop. Then in PowerShell:

```powershell
Copy-Item .env.example .env
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
$env:TOMIRIS_HUB_INGEST_SECRET = python -c "import secrets; print(secrets.token_urlsafe(48))"
$env:TOMIRIS_HUB_INGEST_SECRET
docker compose up -d postgres
python -m alembic upgrade head
python scripts/sync_agent_registry.py
$env:TOMIRIS_TEST_SNAPSHOT_ID = python scripts/create_test_snapshot.py
uvicorn tomiris_hub.main:app --reload
```

In a second PowerShell window:

```powershell
.\.venv\Scripts\Activate.ps1
$env:TOMIRIS_HUB_INGEST_KEY_ID = "current"
$env:TOMIRIS_HUB_INGEST_SECRET = Read-Host "Paste the same generated secret"
$env:TOMIRIS_TEST_SNAPSHOT_ID = "<snapshot id printed above>"
python agents/test_agent/send_signal.py
Invoke-RestMethod http://127.0.0.1:8000/health/live
Invoke-RestMethod http://127.0.0.1:8000/health/ready
pytest -q
```

Paste the generated secret into `.env` only if the Hub itself will run through Docker Compose;
never commit `.env`. To exercise the default safe notification path:

```powershell
python scripts/create_system_test_notification.py
python scripts/run_notification_worker.py
```

Telegram remains disabled unless `TELEGRAM_ENABLED=true`, `TELEGRAM_BOT_TOKEN`, and
`TELEGRAM_CHAT_ID` are explicitly provided. It is outbound-only.

For the implemented boundaries, start with
[`docs/ANALYTICAL_AGENT_FRAMEWORK.md`](docs/ANALYTICAL_AGENT_FRAMEWORK.md),
[`docs/MARKET_DATA_PLANE.md`](docs/MARKET_DATA_PLANE.md),
[`docs/MARKET_SNAPSHOT_SPEC.md`](docs/MARKET_SNAPSHOT_SPEC.md) and
[`docs/MASTER_ARCHITECTURE.md`](docs/MASTER_ARCHITECTURE.md). Phase 03 deliberately does not use
LLMs, and Phase 04 does not make trade decisions, learn, access accounts or execute orders.
