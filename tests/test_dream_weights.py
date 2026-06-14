"""Tests for nested dreaming.weights resolution in DreamEngine."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from braindrain.dream import DreamEngine


def _engine(config: dict) -> DreamEngine:
    return DreamEngine(
        observer_store=MagicMock(),
        session_store=MagicMock(),
        wiki_brain=MagicMock(),
        config={**config, "storage_dir": str(Path("/tmp/braindrain-dream-test"))},
        provider_context={},
    )


def test_scoring_weights_defaults_when_weights_omitted():
    engine = _engine({})
    weights = engine._scoring_weights()
    assert weights["frequency"] == 0.24
    assert weights["relevance"] == 0.30
    assert weights["conceptual_richness"] == 0.06


def test_scoring_weights_from_nested_config():
    engine = _engine(
        {
            "weights": {
                "frequency": 0.5,
                "relevance": 0.1,
                "query_diversity": 0.1,
                "recency": 0.1,
                "consolidation": 0.1,
                "conceptual_richness": 0.1,
            }
        }
    )
    weights = engine._scoring_weights()
    assert weights["frequency"] == 0.5
    assert weights["relevance"] == 0.1


def test_build_consolidation_plan_uses_nested_weights():
    engine = _engine({"weights": {"frequency": 0.99}})
    plan = engine._build_consolidation_plan(mode="full", episodes=[], recent_events=[])
    assert plan.scoring_weights["frequency"] == 0.99


def test_nested_weights_win_over_legacy_dotted_keys():
    """Regression: nested weights dict must beat legacy weights.<key> dotted keys."""
    engine = _engine(
        {
            "weights": {"frequency": 0.5, "relevance": 0.2},
            "weights.frequency": 0.99,
            "weights.relevance": 0.88,
        }
    )
    weights = engine._scoring_weights()
    assert weights["frequency"] == 0.5
    assert weights["relevance"] == 0.2
