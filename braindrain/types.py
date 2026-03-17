"""Type definitions for BRAINDRAIN"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class MCPToolConfig:
    name: str
    command: str
    transport: str = "stdio"
    url: Optional[str] = None
    hot: bool = False
    defer_loading: bool = True
    tags: list[str] = field(default_factory=list)
    description: str = ""
    input_examples: list[dict] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    token_weight: str = "medium"


@dataclass
class WorkflowConfig:
    name: str
    description: str
    steps: list[str]
    executes_in: str = "sandbox"
    model: str = "tier_local"
    token_budget: int = 2000
    plan_before_run: bool = False
    input_examples: list[dict] = field(default_factory=list)


@dataclass
class ModelTier:
    provider: str
    model: str
    api_base: Optional[str] = None
    use_for: list[str] = field(default_factory=list)
    cost_per_1k_input: float = 0.0
    cost_per_1k_output: float = 0.0
    max_tokens: int = 4096


@dataclass
class ConfigData:
    version: str
    project_name: str
    modules: dict
    mcp_tools: list[MCPToolConfig] = field(default_factory=list)
    workflows: list[WorkflowConfig] = field(default_factory=list)
    models: dict[str, ModelTier] = field(default_factory=dict)
    complexity_router: dict = field(default_factory=dict)
    cache: dict = field(default_factory=dict)
    cost_tracking: dict = field(default_factory=dict)
