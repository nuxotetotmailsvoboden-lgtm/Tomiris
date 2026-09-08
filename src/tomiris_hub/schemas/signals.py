"""Backward-compatible imports for protocol 1.0 clients."""

from tomiris_core_contracts.signals import (
    MAX_EVIDENCE_ITEMS,
    MAX_EVIDENCE_SUMMARY,
    AgentSignal,
    Bias,
    EvidenceItem,
    SignalEnvelope,
)

__all__ = [
    "MAX_EVIDENCE_ITEMS",
    "MAX_EVIDENCE_SUMMARY",
    "AgentSignal",
    "Bias",
    "EvidenceItem",
    "SignalEnvelope",
]
