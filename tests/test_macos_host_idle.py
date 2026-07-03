"""Tests for macOS HID idle probing."""

from __future__ import annotations

from unittest.mock import patch

from braindrain import macos_host_idle


def test_get_hid_idle_seconds_parses_ioreg_output():
    sample = '"HIDIdleTime" = 150000000000'
    with patch.object(macos_host_idle, "is_macos", return_value=True):
        with patch.object(
            macos_host_idle.subprocess,
            "run",
            return_value=type("R", (), {"stdout": sample})(),
        ):
            idle = macos_host_idle.get_hid_idle_seconds()
    assert idle == 150.0


def test_get_hid_idle_seconds_none_off_macos():
    with patch.object(macos_host_idle, "is_macos", return_value=False):
        assert macos_host_idle.get_hid_idle_seconds() is None
