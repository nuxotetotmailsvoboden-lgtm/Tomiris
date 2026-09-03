# TOMIRIS — Phase 01 Secure Hub

Phase 01 is only a secure, append-only signal ingestion foundation. It contains no market data, trading, exchange credentials, LLMs, or decisions.

## Windows quick start

1. Install Python 3.12+, Git and Docker Desktop. Then in PowerShell:

```powershell
Copy-Item .env.example .env
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
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
$env:TOMIRIS_HUB_INGEST_SECRET = "replace-with-at-least-32-random-characters-for-local-development"
$env:TOMIRIS_TEST_SNAPSHOT_ID = "<snapshot id printed above>"
python agents/test_agent/send_signal.py
Invoke-RestMethod http://127.0.0.1:8000/health/live
Invoke-RestMethod http://127.0.0.1:8000/health/ready
pytest -q
```

For the complete architecture, protocol, security model and operations, see `docs/`.

