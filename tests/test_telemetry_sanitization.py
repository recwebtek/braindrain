"""Regression tests for telemetry sanitization and redaction."""

from __future__ import annotations

from pathlib import Path

from braindrain.telemetry import TelemetrySession


def _session(tmp_path: Path) -> TelemetrySession:
    return TelemetrySession(log_file=tmp_path / "session.jsonl")


def test_redacts_user_paths(tmp_path: Path) -> None:
    session = _session(tmp_path)
    result = session.sanitize("/Users/ettienne/.braindrain/secret.json")
    assert result == "/Users/[REDACTED_PATH]"


def test_redacts_api_keys_and_cloud_tokens(tmp_path: Path) -> None:
    session = _session(tmp_path)
    slack_token = "-".join(("xoxb", "0" * 10, "0" * 13, "z" * 11))
    payload = {
        "openai": "sk-" + ("a" * 32),
        "aws": "AKIA" + ("A" * 16),
        "slack": slack_token,
    }
    sanitized = session.sanitize(payload)
    assert sanitized["openai"] == "[REDACTED_KEY]"
    assert sanitized["aws"] == "[REDACTED_KEY]"
    assert sanitized["slack"] == "[REDACTED_KEY]"


def test_redacts_generic_secret_assignments(tmp_path: Path) -> None:
    session = _session(tmp_path)
    raw = 'config api_key="super-secret-value" and password: hunter2'
    sanitized = session.sanitize(raw)
    assert "super-secret-value" not in sanitized
    assert "hunter2" not in sanitized
    assert "[REDACTED_SECRET]" in sanitized


def test_redacts_sensitive_dict_keys_without_touching_telemetry_fields(tmp_path: Path) -> None:
    session = _session(tmp_path)
    payload = {
        "tokens_saved_est": 42,
        "tokens_in_raw_est": 100,
        "api_key": "abc123",
        "nested": {"access_token": "tok_live_abc"},
    }
    sanitized = session.sanitize(payload)
    assert sanitized["tokens_saved_est"] == 42
    assert sanitized["tokens_in_raw_est"] == 100
    assert sanitized["api_key"] == "[REDACTED_SECRET]"
    assert sanitized["nested"]["access_token"] == "[REDACTED_SECRET]"


def test_sanitizes_dict_keys_and_tuples(tmp_path: Path) -> None:
    session = _session(tmp_path)
    openai_key = "sk-" + ("a" * 32)
    payload = {
        "/Users/ettienne/project": (openai_key, "ok"),
        "items": [("password", "secret123")],
    }
    sanitized = session.sanitize(payload)
    assert "/Users/[REDACTED_PATH]" in sanitized
    assert sanitized["items"][0][1] == "[REDACTED_SECRET]"


def test_redacts_non_string_sensitive_values(tmp_path: Path) -> None:
    session = _session(tmp_path)
    payload = {
        "password": 123456,
        "api_key": None,
        "token": {"secret": True},
        "nested": [("credentials", 999)],
    }
    sanitized = session.sanitize(payload)
    assert sanitized["password"] == "[REDACTED_SECRET]"
    assert sanitized["api_key"] == "[REDACTED_SECRET]"
    assert sanitized["token"] == "[REDACTED_SECRET]"
    assert sanitized["nested"][0][1] == "[REDACTED_SECRET]"


def test_record_persists_sanitized_jsonl(tmp_path: Path) -> None:
    session = _session(tmp_path)
    session.record(
        tool_name="route_output",
        raw_text="x" * 40,
        actual_text="y" * 10,
        meta={"path": "/Users/ettienne/.env", "api_key": "abc123"},
    )
    line = session.log_file.read_text(encoding="utf-8").strip()
    assert "/Users/ettienne/.env" not in line
    assert "abc123" not in line
    assert "[REDACTED_PATH]" in line
    assert "[REDACTED_SECRET]" in line
