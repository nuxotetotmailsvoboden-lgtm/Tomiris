from __future__ import annotations

import argparse
import os

from tomiris_common.crypto import derive_agent_secret


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Derive one TOMIRIS agent key without persisting the root or result."
    )
    parser.add_argument("agent_id")
    parser.add_argument("purpose", choices=("hub-ingest", "orchestrator-command"))
    parser.add_argument("--key-id", default="current")
    arguments = parser.parse_args()
    root_name = (
        "TOMIRIS_HUB_AGENT_MASTER_SECRET"
        if arguments.purpose == "hub-ingest"
        else "TOMIRIS_ORCHESTRATOR_AGENT_MASTER_SECRET"
    )
    root = os.environ.get(root_name)
    if root is None:
        parser.error(f"{root_name} is not configured")
    print(derive_agent_secret(root, arguments.agent_id, arguments.purpose, arguments.key_id))


if __name__ == "__main__":
    main()
