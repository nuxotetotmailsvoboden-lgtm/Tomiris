# Notification specification

`NotificationEvent` is an outbound-only, transport-neutral contract with event, optional snapshot,
idempotency, correlation, causation, recipient, channel, bounded payload, and UTC creation time.
Phase 01 can create only an explicitly labelled `TOMIRIS_SYSTEM_TEST`; it does not fabricate trade
messages.

Enqueue occurs in the producer's PostgreSQL transaction with a unique idempotency key. Workers use
row locks with `SKIP LOCKED`, set a time-bounded `SENDING` lease, and send outside the database
transaction. Success becomes `SENT`; retryable timeout/network/429/5xx failures use bounded
exponential backoff with jitter and end in `DEAD_LETTER`; permanent 4xx becomes `FAILED`.

Delivery is at least once. A crash after Telegram accepts a request but before `SENT` can produce a
duplicate. Telegram is disabled by default, reads its token/chat only from environment, accepts no
commands, and has no core/database/exchange authority. Null and Console senders support safe local
operation.

## Future trade lifecycle display (not produced in Phase 01)

A future notification may display a centrally issued persistent number (`#000001`, never an
in-memory/Space/Telegram counter), asset, LONG/SHORT, entry zone, TP1/TP2/TP3, stop loss,
invalidation, leverage, position size, risk, confidence, strategy, market regime, timeframes, Chief
opinion, analyst consensus, reasons, risks, daily/weekly PnL, and Asia/Aqtobe timestamp. The Trade
Lifecycle domain—not Telegram—will allocate the number. Phase 01 sends only `TOMIRIS SYSTEM TEST`.
