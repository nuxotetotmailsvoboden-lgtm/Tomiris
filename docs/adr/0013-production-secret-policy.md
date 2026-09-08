# ADR 0013: production secret policy

Status: accepted.

Require at least 32 characters and reject known placeholders, development/test markers, and a
single repeated character in production. This is a practical startup guard, not a mathematical
entropy proof. Secrets remain environment-only and rotation supports one temporary previous key.
