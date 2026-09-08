# ADR 0012: streaming request limit

Status: accepted.

Reject an excessive declared Content-Length before parsing, but do not trust it: count every ASGI
body chunk and stop once the configured byte ceiling is crossed. HMAC and JSON validation operate
only on the bounded exact bytes.
