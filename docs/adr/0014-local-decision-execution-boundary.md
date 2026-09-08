# ADR 0014: local decision and execution boundary

Status: accepted as a future constraint.

Future Orchestrator, Chief, Judge, Risk, and Execution run in a local privileged boundary. Cloud
agents receive neither database nor exchange credentials. Binance credentials may exist only in
Execution. No such subsystem is implemented in Phase 01.
