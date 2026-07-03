#!/usr/bin/env python3
"""One-shot macOS host-idle dream watcher for launchd or manual runs."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def main() -> int:
    repo_root = _repo_root()
    config_path = Path(
        os.environ.get(
            "BRAINDRAIN_CONFIG",
            str(repo_root / "config" / "hub_config.yaml"),
        )
    )
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    from braindrain.dream_trigger import evaluate_host_idle_trigger

    result = evaluate_host_idle_trigger(
        repo_root=repo_root,
        config_path=config_path,
    )
    json.dump(result, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")

    status = result.get("status", "")
    if status in {
        "ran",
        "disabled",
        "skipped_not_idle",
        "skipped_cooldown",
        "skipped_active_session",
        "skipped_lock_held",
    }:
        return 0
    if status in {"unsupported_platform", "idle_probe_failed"}:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
