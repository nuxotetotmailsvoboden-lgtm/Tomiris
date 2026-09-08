---
title: TOMIRIS Universal Agent Runtime
sdk: docker
app_port: 7860
---

This is the single TOMIRIS Universal Runtime template. Configure identity, role, capabilities,
assets and the two purpose-separated agent secrets in Space Settings. Do not fork the runtime
logic per agent. See `docs/HF_AGENT_RUNTIME.md` in the TOMIRIS repository.

The TOMIRIS dependency is pinned to the immutable `v0.3-pilot-agents-pass` release. This tag is
created by the owner only after final review; pre-release CI validates the current source tree and
does not attempt to fetch the not-yet-created remote tag. Never point a production Space at `main`
or a feature branch.

For a Phase 03 analytical deployment, add exactly one reviewed agent-definition YAML to this Space
and set `TOMIRIS_RUNTIME_MODE=analytical` plus
`TOMIRIS_AGENT_DEFINITION_PATH=/app/<definition>.yaml`. Each Space can upgrade or roll back
independently by selecting a compatible certified tag. Existing Phase 02 deployments may remain on
`v0.2-orchestrator-pass`; BTC/ETH/SOL Phase 03 deployments require
`v0.3-pilot-agents-pass` or a later compatible certified release. The definition contains no
secrets.
