"""Shared pytest fixtures and path setup."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def pytest_collection_modifyitems(config, items) -> None:
    if os.environ.get("CI"):
        skip_local = pytest.mark.skip(reason="local_only tests are skipped in CI")
        for item in items:
            if "local_only" in item.keywords:
                item.add_marker(skip_local)
