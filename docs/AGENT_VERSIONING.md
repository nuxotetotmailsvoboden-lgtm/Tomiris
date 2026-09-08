# Analytical versioning and compatibility

| Layer | Phase 03 value | Compatibility rule |
| --- | --- | --- |
| Runtime | `0.3.0` | deploy from an immutable release tag |
| Role API | `1` | incompatible plugin fails startup/readiness |
| Signal protocol | `1.0` | Phase 03 lineage is additive and nullable for legacy agents |
| Role | e.g. `eth.technical.v1` / `1.0.0` | new behavior receives a new identity/version |
| Feature pipeline | `technical-pipeline.v1` | historical pipeline stays identifiable |
| Feature | e.g. `rsi.wilder.v1` | algorithm changes create v2 |
| Config | e.g. `eth-technical-config.v1` | parameter changes receive a new version |
| Analysis schema | `1` | stored explicitly on analytical signals |
| Confidence model | `deterministic-agreement.v1` | strength semantics are versioned |

Migration 0004 stores critical analytical lineage as first-class nullable signal columns. Legacy
Phase 01/02 signals keep every field null; an analytical signal must supply the whole lineage set.
This all-or-none invariant is enforced by Pydantic and PostgreSQL.

## Deployment release policy

Phase 03 BTC/ETH/SOL analytical Spaces install the immutable
`v0.3-pilot-agents-pass` release, or a later compatible certified release. Production never uses
`main` or a feature branch. Existing Phase 02 deployments may remain on
`v0.2-orchestrator-pass`. Each Space rolls forward independently; rollback restores only that
Space's previous compatible certified tag.
