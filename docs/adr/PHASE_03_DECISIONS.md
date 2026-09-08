# Phase 03 architecture decisions

Status: accepted for owner review.

- Analytical professions are role plugins, separate from Universal Runtime transport/security.
- Provider-neutral market-data contracts isolate roles from Binance.
- Features are deterministic, composable and versioned independently from roles.
- Agent definitions and thresholds are typed, declarative and versioned.
- Runtime, role API, signal, role, pipeline, feature, config and confidence versions are explicit.
- Closed candles are the default; analysis cutoff rejects lookahead.
- `NEUTRAL` means a valid no-edge conclusion; data/provider failure means `ABSTAIN`.
- Pilot technical analytics contain no LLM.
- Each HF Space rolls out independently from an immutable shared code release.
- Parallel role versions remain available for shadow/champion-challenger testing.
- Phase 03 stores analytical lineage but not a raw candle warehouse.
- `AgentSignal` remains an observation and cannot bypass future decision/risk/execution boundaries.
