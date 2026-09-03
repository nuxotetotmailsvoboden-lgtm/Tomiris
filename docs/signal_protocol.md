# Signal Protocol 1.0

`POST /v1/signals` accepts an UTF-8 JSON `SignalEnvelope`.

Required headers: `X-Tomiris-Agent-ID`, `X-Tomiris-Timestamp` (UTC Unix seconds), `X-Tomiris-Nonce` (secure random, at least 128 bits), `X-Tomiris-Key-ID`, `X-Tomiris-Signature`.

Canonical string:

```text
METHOD\nPATH\nAGENT_ID\nTIMESTAMP\nNONCE\nKEY_ID\nSHA256(RAW_BODY)
```

Signature is lowercase hex `HMAC-SHA256(secret, canonical_string)`. Do not decode and reserialize JSON before hashing. Required payload fields are implemented in `tomiris_hub.schemas.signals.SignalEnvelope`: protocol version `1.0`, UUID message/run/snapshot IDs, asset, `LONG|SHORT|NEUTRAL|ABSTAIN`, confidence/impact 0–100, evidence, timestamps and positive TTL.

Success: `202 {status: ACCEPTED, request_id, message_id}`. Rejection returns a generic HTTP error with a machine-readable `detail.code`; it never returns secret or database details. The SDK function `build_signed_headers()` is the reference signing implementation.

