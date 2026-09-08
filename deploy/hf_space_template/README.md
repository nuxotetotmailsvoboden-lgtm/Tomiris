---
title: TOMIRIS Universal Agent Runtime
sdk: docker
app_port: 7860
---

This is the single TOMIRIS Phase 02 runtime template. Configure identity, role, capabilities,
assets and the two purpose-separated agent secrets in Space Settings. Do not fork the runtime
logic per agent. See `docs/HF_AGENT_RUNTIME.md` in the TOMIRIS repository.

The TOMIRIS dependency is pinned to the immutable `v0.2-orchestrator-pass` release. Upgrade a
Space only by reviewing and explicitly replacing that tag with another certified release tag;
never point a production Space at `main` or a feature branch.
