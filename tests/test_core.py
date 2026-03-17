"""Tests for BRAINDRAIN MVP"""

from braindrain.config import Config
from braindrain.tool_registry import ToolRegistry, ToolReference


def test_config_load():
    """Test config loading"""
    config = Config("config/hub_config.yaml")
    assert config.get("project_name") == "braindrain"
    assert len(config.mcp_tools) == 4


def test_tool_registry():
    """Test tool registry"""
    config = Config("config/hub_config.yaml")
    registry = ToolRegistry(config.data)

    assert registry.count() == 4
    assert len(registry.get_hot_tools()) == 1
    assert registry.get_hot_tools()[0].name == "context_mode"


def test_tool_search():
    """Test BM25 search"""
    config = Config("config/hub_config.yaml")
    registry = ToolRegistry(config.data)

    results = registry.search("codebase")
    assert len(results) > 0
    assert any("codebase" in r.get("tags", []) for r in results)


def test_tool_defer_loading():
    """Test defer_loading flags"""
    config = Config("config/hub_config.yaml")
    registry = ToolRegistry(config.data)

    for tool in registry.get_deferred_tools():
        assert tool.defer_loading == True

    for tool in registry.get_hot_tools():
        assert tool.hot == True


if __name__ == "__main__":
    test_config_load()
    test_tool_registry()
    test_tool_search()
    test_tool_defer_loading()
    print("All tests passed!")
