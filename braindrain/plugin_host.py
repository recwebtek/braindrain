"""Generic plugin host contract and loader for Braindrain."""

from __future__ import annotations

from dataclasses import dataclass
import importlib.util
import traceback
from pathlib import Path
from typing import Any, Callable, Protocol


CURRENT_PLUGIN_API_VERSION = "1.0"
SUPPORTED_MINOR_WINDOW = {"1.0", "1.1"}


class PluginRuntime(Protocol):
    """Runtime contract every loaded plugin instance must implement."""

    def register_tools(self, registry: "PluginToolRegistry") -> None:
        ...

    def healthcheck(self) -> dict[str, Any]:
        ...

    def shutdown(self) -> None:
        ...


class PluginModule(Protocol):
    """Module-level plugin contract."""

    plugin_api_version: str

    def discover(self) -> dict[str, Any]:
        ...

    def load(self, context: dict[str, Any]) -> PluginRuntime:
        ...


@dataclass
class PluginToolSpec:
    name: str
    handler: Callable[..., Any]
    description: str = ""


@dataclass
class PluginRuntimeHandle:
    name: str
    path: Path
    api_version: str
    runtime: PluginRuntime
    metadata: dict[str, Any]


class PluginToolRegistry:
    """Tool collection interface passed to plugins."""

    def __init__(self) -> None:
        self._tools: dict[str, PluginToolSpec] = {}

    def register(self, name: str, handler: Callable[..., Any], description: str = "") -> None:
        if name in self._tools:
            raise ValueError(f"tool already registered: {name}")
        self._tools[name] = PluginToolSpec(name=name, handler=handler, description=description)

    def tools(self) -> dict[str, PluginToolSpec]:
        return dict(self._tools)


class PluginHost:
    """Generic plugin loader/executor with lifecycle and failure isolation."""

    def __init__(self, emit_event: Callable[[str, dict[str, Any]], None] | None = None) -> None:
        self._emit_event = emit_event or (lambda _event, _payload: None)
        self._plugins: dict[str, PluginRuntimeHandle] = {}
        self._tool_to_plugin: dict[str, str] = {}
        self._tools: dict[str, PluginToolSpec] = {}

    def load_plugin(self, name: str, module_path: Path, context: dict[str, Any]) -> dict[str, Any]:
        module_path = module_path.expanduser().resolve()
        if not module_path.exists():
            payload = {
                "status": "plugin_load_failed",
                "plugin": name,
                "error_code": "plugin_path_not_found",
                "message": f"Plugin path not found: {module_path}",
            }
            self._emit_event("plugin_load_failed", payload)
            return payload

        try:
            module = self._load_module(name=name, module_path=module_path)
            api_version = str(getattr(module, "plugin_api_version", "")).strip()
            if not self._is_supported_version(api_version):
                payload = {
                    "status": "plugin_load_failed",
                    "plugin": name,
                    "error_code": "unsupported_plugin_api_version",
                    "message": (
                        f"Unsupported plugin_api_version '{api_version}'. "
                        f"Host supports: {sorted(SUPPORTED_MINOR_WINDOW)}."
                    ),
                }
                self._emit_event("plugin_load_failed", payload)
                return payload

            discover = getattr(module, "discover", None)
            load = getattr(module, "load", None)
            if not callable(discover) or not callable(load):
                payload = {
                    "status": "plugin_load_failed",
                    "plugin": name,
                    "error_code": "invalid_plugin_contract",
                    "message": "Plugin must implement discover() and load(context).",
                }
                self._emit_event("plugin_load_failed", payload)
                return payload

            metadata = discover()
            runtime = load(context)
            handle = PluginRuntimeHandle(
                name=name,
                path=module_path,
                api_version=api_version,
                runtime=runtime,
                metadata=metadata,
            )
            self._plugins[name] = handle
            self._emit_event(
                "plugin_loaded",
                {"plugin": name, "api_version": api_version, "path": str(module_path)},
            )
            return {"status": "plugin_loaded", "plugin": name, "metadata": metadata}
        except Exception as exc:  # pragma: no cover - defensive fallback
            payload = {
                "status": "plugin_load_failed",
                "plugin": name,
                "error_code": "plugin_load_exception",
                "message": str(exc),
                "traceback": traceback.format_exc(),
            }
            self._emit_event("plugin_load_failed", payload)
            return payload

    def register_plugin_tools(self, name: str) -> dict[str, Any]:
        handle = self._plugins.get(name)
        if not handle:
            return {
                "status": "plugin_registration_failed",
                "plugin": name,
                "error_code": "plugin_not_loaded",
                "message": "Plugin is not loaded.",
            }

        registry = PluginToolRegistry()
        try:
            handle.runtime.register_tools(registry)
            registered = []
            for tool_name, spec in registry.tools().items():
                self._tools[tool_name] = spec
                self._tool_to_plugin[tool_name] = name
                registered.append(tool_name)
                self._emit_event(
                    "plugin_tool_registered", {"plugin": name, "tool": tool_name}
                )
            return {"status": "ok", "plugin": name, "tools": registered}
        except Exception as exc:
            payload = {
                "status": "plugin_registration_failed",
                "plugin": name,
                "error_code": "plugin_registration_failed",
                "message": str(exc),
            }
            self._emit_event("plugin_tool_registration_failed", payload)
            return payload

    def invoke_tool(self, tool_name: str, **kwargs: Any) -> Any:
        spec = self._tools.get(tool_name)
        if not spec:
            return {
                "status": "plugin_tool_invocation_failed",
                "error_code": "plugin_tool_not_found",
                "message": f"Unknown plugin tool: {tool_name}",
            }
        try:
            return spec.handler(**kwargs)
        except Exception as exc:
            plugin_name = self._tool_to_plugin.get(tool_name, "unknown")
            payload = {
                "status": "plugin_tool_invocation_failed",
                "plugin": plugin_name,
                "tool": tool_name,
                "error_code": "plugin_runtime_error",
                "message": str(exc),
            }
            self._emit_event("plugin_tool_invocation_failed", payload)
            return payload

    def healthcheck(self) -> dict[str, Any]:
        report: dict[str, Any] = {"plugins": {}, "tools": sorted(self._tools.keys())}
        for name, handle in self._plugins.items():
            try:
                report["plugins"][name] = handle.runtime.healthcheck()
            except Exception as exc:
                report["plugins"][name] = {
                    "status": "unhealthy",
                    "error": str(exc),
                }
        return report

    def shutdown(self) -> None:
        for name, handle in list(self._plugins.items()):
            try:
                handle.runtime.shutdown()
                self._emit_event("plugin_shutdown", {"plugin": name})
            except Exception as exc:
                self._emit_event(
                    "plugin_shutdown_failed",
                    {"plugin": name, "error": str(exc)},
                )

    def has_tool(self, tool_name: str) -> bool:
        return tool_name in self._tools

    def _is_supported_version(self, version: str) -> bool:
        return version in SUPPORTED_MINOR_WINDOW

    def _load_module(self, name: str, module_path: Path) -> PluginModule:
        entry_file = module_path / "plugin.py"
        if not entry_file.exists():
            raise FileNotFoundError(f"Missing plugin entrypoint: {entry_file}")
        module_name = f"braindrain_plugin_{name.replace('-', '_')}"
        spec = importlib.util.spec_from_file_location(module_name, entry_file)
        if spec is None or spec.loader is None:
            raise ImportError(f"Could not load plugin module spec from {entry_file}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module  # type: ignore[return-value]
