"""Type definitions for BRAINDRAIN"""

from dataclasses import dataclass, field
from typing import Any, Optional


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
    roles: list[str] = field(default_factory=list)
    bundles: list[str] = field(default_factory=list)


@dataclass
class WorkflowConfig:
    name: str
    description: str
    steps: list[Any]
    executes_in: str = "sandbox"
    model: str = "tier_local"
    token_budget: int = 2000
    plan_before_run: bool = False
    input_examples: list[dict] = field(default_factory=list)
    required_roles: list[str] = field(default_factory=list)
    output_mode: str = "compact"


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
    bundles: dict = field(default_factory=dict)
    agent_capabilities: dict = field(default_factory=dict)
    token_policy: dict = field(default_factory=dict)
    comms: dict = field(default_factory=dict)
    memory_learning: dict = field(default_factory=dict)
    observer: dict = field(default_factory=dict)
    sessions: dict = field(default_factory=dict)
    wiki_brain: dict = field(default_factory=dict)
    lessons: dict = field(default_factory=dict)
    dreaming: dict = field(default_factory=dict)
    provider_context: dict = field(default_factory=dict)
