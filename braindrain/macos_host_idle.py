"""macOS host idle detection via IOHIDSystem (no pyobjc)."""

from __future__ import annotations

import platform
import re
import subprocess


def is_macos() -> bool:
    return platform.system() == "Darwin"


def get_hid_idle_seconds() -> float | None:
    """Return seconds since last keyboard/mouse input, or None if unavailable."""
    if not is_macos():
        return None
    try:
        completed = subprocess.run(
            ["ioreg", "-c", "IOHIDSystem"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r'"HIDIdleTime"\s*=\s*(\d+)', completed.stdout)
    if not match:
        return None
    return int(match.group(1)) / 1_000_000_000.0
