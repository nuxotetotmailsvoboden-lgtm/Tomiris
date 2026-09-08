# Hugging Face Universal Agent Runtime

Every Space uses the same template in `deploy/hf_space_template`. A new Space is a deployment of
the existing runtime, not a new system or copied `spaceN.py` codebase.

The production template pins TOMIRIS to the immutable `v0.2-orchestrator-pass` tag. A moving
branch—including `main` or a feature branch—is never a production dependency. Upgrades are
controlled changes: review a new certified release, replace the pinned tag explicitly (for
example with `v0.3-pilot-agents-pass`), rebuild the Space, and verify its capability handshake.

1. Create a Docker Space and copy the universal template.
2. Confirm `requirements.txt` points to the owner-approved immutable release tag.
3. Set `TOMIRIS_AGENT_ID`, `TOMIRIS_AGENT_ROLE`, `TOMIRIS_AGENT_CAPABILITIES` and
   `TOMIRIS_AGENT_SUPPORTED_ASSETS`.
4. Set `TOMIRIS_HUB_URL`, `TOMIRIS_HUB_KEY_ID` and its agent-specific
   `TOMIRIS_HUB_AGENT_SECRET` as Space secrets.
5. Set `TOMIRIS_ORCHESTRATOR_ID`, `TOMIRIS_ORCHESTRATOR_COMMAND_KEY_ID` and the separate
   `TOMIRIS_ORCHESTRATOR_COMMAND_SECRET` as Space secrets.
6. Register the logical agent and deployment endpoint centrally. The endpoint must be HTTPS in
   production and match the configured host allowlist.
7. Verify live, ready and capabilities handshake. Drift makes runtime state DEGRADED; the registry
   remains authoritative.

The runtime exposes `GET /health/live`, `GET /health/ready`, `GET /v1/capabilities` and signed
`POST /v1/analyze`. Phase 02 installs only `TestAnalysisHandler`; future adapters implement the
same `AnalysisHandler` interface.

Generate each purpose-specific Space secret locally:

```powershell
python scripts/derive_agent_secret.py TEST_AGENT_A hub-ingest --key-id current
python scripts/derive_agent_secret.py TEST_AGENT_A orchestrator-command --key-id current
```

The command reads the selected master root from the environment and prints only the derived key.
Never paste a root secret into a Space. Never commit either secret. Space sleep is handled by cold
start grace and durable retry; self-ping, account rotation, artificial traffic and quota bypass are
not part of TOMIRIS.
