# Temporal Integrity

All internal market timestamps are timezone-aware UTC. TOMIRIS distinguishes:

- `event_time`: logical time used for ordering and cutoff;
- `exchange_time`: provider-reported source time;
- `received_at`: local ingress time;
- `processed_at`: completion of normalization;
- `snapshot.as_of`: immutable logical cutoff.

Events after `as_of` are excluded by the recent store and cannot enter a verified snapshot. Open
candles remain excluded by the Phase 03 `closed_only` policy. An OHLCV window is only valid when
all bars are closed, ordered, identity-consistent, and its final close equals the observation time.

`TimeSource` is the only clock dependency in new Phase 04 core paths. Production uses
`SystemUTCClock`; tests and replay use `DeterministicClock`.

## Clock drift

The futures public server-time endpoint supplies exchange time. `ClockDriftMonitor` estimates
offset against the midpoint of request start and response receipt and records round-trip time. The
default policy is:

- absolute offset below 500 ms: `HEALTHY`;
- 500–1999 ms: `DEGRADED`;
- 2000 ms or more: `UNSAFE`.

Thresholds are configuration, not strategy. `UNSAFE` is a hard quality veto; TOMIRIS measures but
never changes host clocks. Operators should use NTP/chrony and investigate drift metrics.

## Cross-source skew

`SnapshotRequirement.max_temporal_skew_seconds` is explicit per manifest. If the selected event
times exceed it, the snapshot is invalid. Slowly changing sources can receive a separate policy in
a future phase; consumers must never silently widen the cutoff.
