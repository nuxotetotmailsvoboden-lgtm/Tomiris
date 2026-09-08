# ADR 0017: N-agent scalability

Status: accepted.

The initial planned 9 accounts × 3 Spaces is configuration, not architecture. A generic PostgreSQL
registry and versioned protocol support 27, 100, or more identities without core branches. Registry
capabilities and scope authorize each identity; secrets never appear in YAML.
