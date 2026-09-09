# Market Data Failure Policy

| Failure | State/action | Analysis eligibility |
|---|---|---|
| Malformed/oversized payload | Reject with schema/size code | No |
| Unsupported capability | Controlled routing error | No |
| REST 401/403/other 4xx | Non-retryable provider error | No |
| REST timeout/429/selected 5xx | Bounded retry with jitter | No until success |
| WebSocket disconnect | `RECONNECTING`, close resource, bounded retry | No for old book |
| Queue or delta-buffer overflow | `OUT_OF_SYNC`, discard bounded recovery buffer | No |
| Duplicate/old depth delta | Deterministically ignore | Existing synced state retained |
| Depth sequence gap | `OUT_OF_SYNC`, fresh snapshot required | No |
| Stale event | Degraded/invalid according to explicit policy | Policy-dependent |
| Excess temporal skew | Snapshot invalid | No |
| Unsafe clock drift | Quality veto | No |
| Missing optional component | Snapshot degraded | Yes if critical minimum remains |
| Missing required component | Snapshot insufficient | No |
| Private/special DNS result | Abort before socket connection | No |

Failures expose machine-readable codes including `PROVIDER_TIMEOUT`, `PROVIDER_SCHEMA_ERROR`,
`PROVIDER_RESPONSE_TOO_LARGE`, `UNSUPPORTED_CAPABILITY`, `STREAM_MESSAGE_TOO_LARGE`,
`BUFFER_OVERFLOW`, `SEQUENCE_GAP`, `CLOCK_DRIFT_UNSAFE`, and `SNAPSHOT_NOT_ANALYSIS_SAFE`.

No integrity failure maps to `NEUTRAL` market opinion. Retry loops, response bodies, queues, buffers,
and concurrency are bounded. Cancellation closes active stream resources.
