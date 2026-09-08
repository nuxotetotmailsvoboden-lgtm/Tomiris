# How to add an analytical agent

1. Implement a `RolePlugin` and transport-independent `AnalyticalRole` under
   `tomiris_agent_roles`.
2. Declare bounded `RoleDataRequirement` values; add a provider/adapter only for a genuinely new
   data type.
3. Define a typed role config and version every parameter set.
4. Register the plugin in the role-layer registry. Do not modify Runtime, Hub or Orchestrator.
5. Add one reviewed YAML `AgentDefinition` without secrets.
6. Add contract, unit, data-quality, golden, isolation and failure tests.
7. Include the role in an immutable TOMIRIS release. Phase 03 pilot deployments use
   `v0.3-pilot-agents-pass` or a later compatible certified tag—never `main` or a feature branch.
8. Deploy the same Universal Runtime and set identity/config plus purpose-separated secrets.
9. Register the logical agent and HTTPS endpoint centrally.
10. Verify liveness, readiness, capabilities and a signed test orchestration.

For an X/Twitter sentiment, Reddit, order-flow, macro or gold agent, the system-core answer is the
same: add a role plugin, appropriate data adapter/provider, optional features, definition, tests and
deployment config. Secure Hub and Orchestrator do not change.

Existing Phase 02 Spaces can remain on `v0.2-orchestrator-pass`. Deploy or roll back each new Space
independently by changing only its certified release pin; a simultaneous fleet update is not
required.
