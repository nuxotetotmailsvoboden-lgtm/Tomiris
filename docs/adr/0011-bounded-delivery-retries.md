# ADR 0011: bounded delivery retries

Status: accepted.

Timeout/network/429/5xx failures retry with exponential delay, bounded maximum, jitter, and maximum
attempts. Permanent 4xx fails immediately. Expired `SENDING` leases are reclaimable. Exhaustion is
durably visible as `DEAD_LETTER` rather than an infinite loop.
