"""Tests for hub_config.yaml Pydantic schema validation."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from braindrain.config import Config
from braindrain.config_schema import (
    ConfigValidationError,
    validate_hub_config,
    validated_to_raw_dict,
)


def _minimal_config_lines(*extra_lines: str) -> str:
    lines = [
        'version: "1.0"',
        'project_name: "test"',
        "modules: {}",
        "mcp_tools: []",
        "workflows: []",
        "models: {}",
        *extra_lines,
    ]
    return "\n".join(lines) + "\n"


def test_validate_minimal_config_succeeds():
    validated, warnings = validate_hub_config(
        {
            "version": "1.0",
            "project_name": "braindrain",
            "modules": {},
            "mcp_tools": [],
            "workflows": [],
            "models": {},
        }
    )
    assert validated.version == "1.0"
    assert validated.project_name == "braindrain"
    assert warnings == []


def test_shipped_hub_config_yaml_validates():
    root = Path(__file__).resolve().parent.parent
    cfg_path = root / "config" / "hub_config.yaml"
    import yaml

    raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    validated, warnings = validate_hub_config(raw)
    assert validated.version
    assert len(validated.mcp_tools) > 0
    assert validated.dreaming.weights.frequency == 0.24
    assert warnings == []


def test_invalid_workflow_type_raises():
    with pytest.raises(ConfigValidationError, match="workflows"):
        validate_hub_config({"workflows": [{"name": "wf", "token_budget": "nope"}]})


def test_missing_mcp_tool_name_raises():
    with pytest.raises(ConfigValidationError, match="mcp_tools"):
        validate_hub_config({"mcp_tools": [{"command": "echo"}]})


def test_missing_workflow_name_raises():
    with pytest.raises(ConfigValidationError, match="workflows"):
        validate_hub_config({"workflows": [{"description": "no name"}]})


def test_unknown_top_level_key_warns_not_errors(caplog):
    caplog.set_level(logging.WARNING)
    validated, warnings = validate_hub_config(
        {
            "version": "1.0",
            "future_section": {"enabled": True},
            "mcp_tools": [],
        }
    )
    assert validated.version == "1.0"
    assert any("future_section" in message for message in warnings)
    assert any("future_section" in record.message for record in caplog.records)


def test_livingdash_block_ignored_with_warning(caplog):
    caplog.set_level(logging.WARNING)
    validated, warnings = validate_hub_config(
        {
            "version": "1.0",
            "livingdash": {"enabled": True},
            "mcp_tools": [],
        }
    )
    assert validated.version == "1.0"
    assert any("livingdash" in message for message in warnings)
    assert "livingdash" not in validated_to_raw_dict(validated)


def test_dreaming_weights_nested_dict_validates():
    validated, _ = validate_hub_config(
        {
            "dreaming": {
                "weights": {
                    "frequency": 0.5,
                    "relevance": 0.1,
                }
            }
        }
    )
    assert validated.dreaming.weights.frequency == 0.5
    assert validated.dreaming.weights.relevance == 0.1
    dumped = validated_to_raw_dict(validated)
    assert dumped["dreaming"]["weights"]["frequency"] == 0.5


def test_config_loader_fails_fast_on_invalid_yaml(tmp_path: Path):
    cfg_path = tmp_path / "hub_config.yaml"
    cfg_path.write_text(
        _minimal_config_lines("workflows:", "  - name: wf", '    token_budget: "nope"'),
        encoding="utf-8",
    )
    with pytest.raises(ConfigValidationError):
        Config(cfg_path)


def test_config_loader_accepts_valid_minimal_yaml(tmp_path: Path):
    cfg_path = tmp_path / "hub_config.yaml"
    cfg_path.write_text(_minimal_config_lines(), encoding="utf-8")
    config = Config(cfg_path)
    assert config.data.version == "1.0"
    assert config.data.project_name == "test"


def test_config_loader_warns_on_unknown_keys(tmp_path: Path, caplog):
    caplog.set_level(logging.WARNING)
    cfg_path = tmp_path / "hub_config.yaml"
    cfg_path.write_text(
        _minimal_config_lines("experimental_feature: true"),
        encoding="utf-8",
    )
    config = Config(cfg_path)
    assert config.data.version == "1.0"
    assert any("experimental_feature" in record.message for record in caplog.records)


def test_planning_auditor_section_validates():
    validated, _ = validate_hub_config(
        {
            "planning_auditor": {
                "overlap_jaccard_threshold": 0.6,
                "apply_overlap_relations": True,
            }
        }
    )
    assert validated.planning_auditor.overlap_jaccard_threshold == 0.6
    assert validated.planning_auditor.apply_overlap_relations is True
