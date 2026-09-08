# Hugging Face Universal Agent Runtime

Every Space uses the same template in `deploy/hf_space_template`. A new Space is a deployment of
the existing runtime, not a new system or copied `spaceN.py` codebase.

The Phase 03 production template pins TOMIRIS to the immutable `v0.3-pilot-agents-pass` tag. A
moving branch—including `main` or a feature branch—is never a production dependency. Existing
Phase 02 deployments may remain on `v0.2-orchestrator-pass`. BTC, ETH and SOL analytical
deployments require `v0.3-pilot-agents-pass` or a later compatible certified release.

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
`POST /v1/analyze`. Test deployments use `TestAnalysisHandler`. Phase 03 analytical deployments
set `TOMIRIS_RUNTIME_MODE=analytical` and provide one reviewed `TOMIRIS_AGENT_DEFINITION_PATH`;
Runtime loads the declared plugin through the role registry without asset-specific core branches.

For an analytical Space, copy exactly one definition file into the Space repository, ensure the
Docker build includes it, and point the environment variable at that file. Identity, role,
capabilities and assets in environment and definition must match or startup fails. Public provider
settings are non-secret; the pilot uses HTTPS Binance public endpoints with no exchange key.

Generate each purpose-specific Space secret locally:

```powershell
python scripts/derive_agent_secret.py TEST_AGENT_A hub-ingest --key-id current
python scripts/derive_agent_secret.py TEST_AGENT_A orchestrator-command --key-id current
```

The command reads the selected master root from the environment and prints only the derived key.
Never paste a root secret into a Space. Never commit either secret. Space sleep is handled by cold
start grace and durable retry; self-ping, account rotation, artificial traffic and quota bypass are
not part of TOMIRIS.

The owner creates `v0.3-pilot-agents-pass` only after release review. Until then, deterministic CI
validates the local source and must not try to install the absent remote tag. Roll out each Space
independently; no fleet-wide upgrade is required. Rollback means pinning only the affected Space to
its previous compatible certified tag and rebuilding it.
