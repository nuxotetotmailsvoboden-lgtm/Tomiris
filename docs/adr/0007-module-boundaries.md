# ADR 0007: dependency boundaries

Status: accepted.

Use `tomiris_common`, `tomiris_core_contracts`, `tomiris_hub`, and
`tomiris_notifications` as one-way boundaries. Contracts/common do not import runtime services;
the Hub never imports Telegram. This prevents transport details from acquiring business authority.
