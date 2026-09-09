# Verified Market Snapshot Specification

`VerifiedMarketSnapshotBuilder` creates one bounded logical view for a supplied UUID and UTC
`as_of`. `SnapshotRequirement` declares instrument, data type, required/optional status, maximum
age, optional minimum book depth, OHLCV timeframe qualifier, maximum temporal skew, and policy
version. No asset-specific decision logic is embedded.

The builder selects only events with `event_time <= as_of`. Every selected event needs a structured
quality report. Missing quality is invalid rather than assumed valid. Missing required data yields
`INSUFFICIENT`; missing optional data yields `DEGRADED`; invalid required data, excessive skew, or
unsafe clock drift makes the manifest non-analysis-safe.

The immutable manifest contains:

- snapshot ID, cutoff, creation time, schema and policy version;
- canonical instrument, provider, and data-type sets;
- component event IDs, time ranges, receive/event timestamps, and schema versions;
- component quality states and missing required/optional keys;
- provenance references and SHA-256 component hashes;
- aggregate quality, temporal skew, analysis-safety flag, and content fingerprint.

The content fingerprint uses sorted canonical JSON and SHA-256, never Python's process-randomized
`hash()`. It excludes operational creation time and snapshot UUID, so identical content, cutoff,
policy, and quality produce the same fingerprint. Any component-content change changes the digest.

`require_analysis_safe()` is the explicit boundary before an analytical task. Existing Hub and
Orchestrator behavior then reinforces the veto: only an `OPEN`, non-expired durable snapshot is
eligible. Phase 04 E2E stores invalid manifests as `INVALID`, which the Orchestrator rejects before
task creation.
