# How to upgrade one agent

Example `eth.technical.v1` to `eth.technical.v2`:

1. Add the v2 plugin with a distinct immutable role and feature-pipeline version; retain v1.
2. Add a new typed config version and golden tests.
3. Shadow-test v2 against identical snapshot/cutoff data; do not use trade outcomes for automatic
   learning in Phase 03.
4. Publish an owner-approved immutable code release.
5. Rebuild only the selected ETH Space and change its reviewed `AgentDefinition`.
6. Compare v1/v2 analytical records by first-class lineage.
7. Roll back that Space to v1 if required. BTC, SOL, Hub and Orchestrator remain untouched.

`ACTIVE`, `DEPRECATED` and `DISABLED` describe role lifecycle. A deprecated version stays loadable
for replay/shadow compatibility but must not be selected for a new production rollout; `DISABLED`
fails closed in the registry. Neither state erases the old plugin/version or historical signals.
V1 and v2 can coexist for future champion/challenger operation.
