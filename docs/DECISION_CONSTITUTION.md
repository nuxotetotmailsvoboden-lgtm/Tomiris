# Decision constitution

This is a future-phase constraint, not an implemented decision engine.

1. Abstention is always valid; confidence never creates permission to trade.
2. Evidence count is not independence. Shared provider, source ID, fingerprint, or upstream origin
   must be de-duplicated before future voting.
3. Correlation IDs trace work; causation IDs express lineage, not proven causality.
4. Stale, invalid, incompatible, or missing snapshots are ineligible.
5. Deterministic risk constraints must be able to veto any analytical output.
6. No LLM or notification channel may directly execute an order.
7. Every future decision must be reproducible from versioned inputs, policy, and code.

Phase 01 only stores validated observations. It does not score, combine, debate, or decide.
