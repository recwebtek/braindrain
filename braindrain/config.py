"""Configuration loader with hot-reload support"""

import os
import yaml
from pathlib import Path
from typing import Optional, Any
from dataclasses import asdict

try:
    from watchfiles import watch

    WATCHFILES_AVAILABLE = True
except ImportError:
    WATCHFILES_AVAILABLE = False

from braindrain.types import ConfigData, MCPToolConfig, WorkflowConfig, ModelTier


class Config:
    """Configuration loader with hot-reload capability"""

    def __init__(self, config_path: str | Path):
        self.config_path = Path(config_path)
        self._config: Optional[ConfigData] = None
        self._callbacks: list[callable] = []
        self._load()

    def _load(self) -> None:
        """Load configuration from YAML file"""
        if not self.config_path.exists():
            raise FileNotFoundError(f"Config file not found: {self.config_path}")

        with open(self.config_path, "r") as f:
            raw = yaml.safe_load(f)

        self._config = self._parse_config(raw)

    def _parse_config(self, raw: dict) -> ConfigData:
        """Parse raw YAML into ConfigData"""
        mcp_tools = []
        for tool in raw.get("mcp_tools", []):
            mcp_tools.append(
                MCPToolConfig(
                    name=tool["name"],
                    command=tool.get("command", ""),
                    transport=tool.get("transport", "stdio"),
                    url=tool.get("url"),
                    hot=tool.get("hot", False),
                    defer_loading=tool.get("defer_loading", True),
                    tags=tool.get("tags", []),
                    description=tool.get("description", ""),
                    input_examples=tool.get("input_examples", []),
                    env=tool.get("env", {}),
                    token_weight=tool.get("token_weight", "medium"),
                    roles=tool.get("roles", []),
                    bundles=tool.get("bundles", []),
                )
            )

        workflows = []
        for wf in raw.get("workflows", []):
            workflows.append(
                WorkflowConfig(
                    name=wf["name"],
                    description=wf.get("description", ""),
                    steps=wf.get("steps", []),
                    executes_in=wf.get("executes_in", "sandbox"),
                    model=wf.get("model", "tier_local"),
                    token_budget=wf.get("token_budget", 2000),
                    plan_before_run=wf.get("plan_before_run", False),
                    input_examples=wf.get("input_examples", []),
                    required_roles=wf.get("required_roles", []),
                    output_mode=wf.get("output_mode", "compact"),
                )
            )

        models = {}
        for name, tier in raw.get("models", {}).items():
            models[name] = ModelTier(
                provider=tier.get("provider", "ollama"),
                model=tier.get("model", ""),
                api_base=tier.get("api_base"),
                use_for=tier.get("use_for", []),
                cost_per_1k_input=tier.get("cost_per_1k_input", 0.0),
                cost_per_1k_output=tier.get("cost_per_1k_output", 0.0),
                max_tokens=tier.get("max_tokens", 4096),
            )

        return ConfigData(
            version=raw.get("version", "1.0"),
            project_name=raw.get("project_name", "braindrain"),
            modules=raw.get("modules", {}),
            mcp_tools=mcp_tools,
            workflows=workflows,
            models=models,
            complexity_router=raw.get("complexity_router", {}),
            cache=raw.get("cache", {}),
            cost_tracking=raw.get("cost_tracking", {}),
            bundles=raw.get("bundles", {}),
            agent_capabilities=raw.get("agent_capabilities", {}),
            token_policy=raw.get("token_policy", {}),
            comms=raw.get("comms", {}),
            memory_learning=raw.get("memory_learning", {}),
            observer=raw.get("observer", {}),
            sessions=raw.get("sessions", {}),
            wiki_brain=raw.get("wiki_brain", {}),
            lessons=raw.get("lessons", {}),
            dreaming=raw.get("dreaming", {}),
            provider_context=raw.get("provider_context", {}),
        )

    def reload(self) -> None:
        """Reload configuration from file"""
        old_config = self._config
        self._load()
        for callback in self._callbacks:
            callback(old_config, self._config)

    def on_change(self, callback: callable) -> None:
        """Register a callback to be called when config changes"""
        self._callbacks.append(callback)

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value by dot-notation key"""
        keys = key.split(".")
        value = self._config
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            elif hasattr(value, k):
                value = getattr(value, k)
            else:
                return default
        return value

    @property
    def data(self) -> ConfigData:
        """Get full config data"""
        return self._config

    @property
    def mcp_tools(self) -> list[MCPToolConfig]:
        """Get list of MCP tool configs"""
        return self._config.mcp_tools

    @property
    def workflows(self) -> list[WorkflowConfig]:
        """Get list of workflow configs"""
        return self._config.workflows

    def get_tool(self, name: str) -> Optional[MCPToolConfig]:
        """Get a specific tool config by name"""
        for tool in self._config.mcp_tools:
            if tool.name == name:
                return tool
        return None

    def get_workflow(self, name: str) -> Optional[WorkflowConfig]:
        """Get a specific workflow config by name"""
        for wf in self._config.workflows:
            if wf.name == name:
                return wf
        return None

    def get_workflow_catalog(self) -> dict:
        """Get workflow catalog for list_workflows tool"""
        return {
            "workflows": [
                {
                    "name": wf.name,
                    "description": wf.description,
                    "token_budget": wf.token_budget,
                    "steps": wf.steps,
                }
                for wf in self._config.workflows
            ],
            "count": len(self._config.workflows),
        }


def load_config(config_path: str | Path) -> Config:
    """Convenience function to load configuration"""
    return Config(config_path)
