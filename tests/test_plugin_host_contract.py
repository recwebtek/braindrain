from __future__ import annotations

import textwrap
from pathlib import Path

from braindrain.plugin_host import PluginHost


def _write_plugin(path: Path, body: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "plugin.py").write_text(body, encoding="utf-8")


def test_plugin_host_loads_and_registers_tools(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "demo_plugin"
    _write_plugin(
        plugin_dir,
        textwrap.dedent(
            """
            plugin_api_version = "1.0"

            def discover():
                return {"name": "demo"}

            class Runtime:
                def register_tools(self, registry):
                    registry.register("demo_tool", self.demo_tool, "Demo tool")
                def demo_tool(self, value: str):
                    return {"value": value}
                def healthcheck(self):
                    return {"status": "ok"}
                def shutdown(self):
                    return None

            def load(context):
                return Runtime()
            """
        ),
    )
    host = PluginHost()
    loaded = host.load_plugin("demo", plugin_dir, {"repo_root": str(tmp_path)})
    assert loaded["status"] == "plugin_loaded"
    reg = host.register_plugin_tools("demo")
    assert reg["status"] == "ok"
    assert "demo_tool" in reg["tools"]
    result = host.invoke_tool("demo_tool", value="x")
    assert result == {"value": "x"}


def test_plugin_host_fails_closed_on_version_mismatch(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "bad_plugin"
    _write_plugin(
        plugin_dir,
        textwrap.dedent(
            """
            plugin_api_version = "9.9"
            def discover(): return {"name": "bad"}
            def load(context): return object()
            """
        ),
    )
    host = PluginHost()
    loaded = host.load_plugin("bad", plugin_dir, {})
    assert loaded["status"] == "plugin_load_failed"
    assert loaded["error_code"] == "unsupported_plugin_api_version"
