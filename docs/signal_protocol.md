# Signal Protocol 1.0

`POST /v1/signals` accepts an UTF-8 JSON `SignalEnvelope`.

Required headers: `X-Tomiris-Agent-ID`, `X-Tomiris-Timestamp` (UTC Unix seconds), `X-Tomiris-Nonce` (secure random, at least 128 bits), `X-Tomiris-Key-ID`, `X-Tomiris-Signature`.

Canonical string:

```text
METHOD\nPATH\nAGENT_ID\nTIMESTAMP\nNONCE\nKEY_ID\nSHA256(RAW_BODY)
```

Signature is lowercase hex `HMAC-SHA256(secret, canonical_string)`. Do not decode and reserialize JSON before hashing. Required payload fields are implemented in `tomiris_core_contracts.signals.SignalEnvelope` and re-exported by the legacy Hub schema path: protocol version `1.0`, UUID message/run/snapshot IDs, optional correlation/causation IDs, asset, `LONG|SHORT|NEUTRAL|ABSTAIN`, confidence/impact 0–100, evidence, UTC timestamps and positive TTL. Evidence records source type/ID/time, provider, and an optional source fingerprint; absent provider defaults to `unknown` for compatible older producers.

Success: `202 {status: ACCEPTED, request_id, message_id}`. Rejection returns a generic HTTP error with a machine-readable `detail.code`; it never returns secret or database details. The SDK function `build_signed_headers()` is the reference signing implementation.

## Phase 03 analytical lineage

Signals produced by an analytical role populate the additive first-class fields `role_id`,
`role_version`, `config_version`, `feature_pipeline_version`, `analysis_schema_version`,
`data_provider`, `data_as_of`, and `confidence_model_version`. These fields are nullable only for
legacy and Phase 02 test producers; when one analytical lineage field is present, the complete set
is required. Evidence may additionally identify the instrument, timeframe, feature name/version,
and bounded observation. The Hub persists these values without treating a signal as a trade
decision.
