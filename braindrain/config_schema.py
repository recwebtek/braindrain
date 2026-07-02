"""Pydantic v2 schema for ``hub_config.yaml`` startup validation.

Forward-compat policy
---------------------
Unknown **top-level** keys are logged as warnings and ignored — they are not
passed to runtime :class:`~braindrain.types.ConfigData`. This allows newer
config sections to ship in YAML without breaking older hub builds.

The ``livingdash:`` block is explicitly excluded (superseded by MCP Apps); if
present it is ignored without validation.

Within known sections, unrecognized nested keys are ignored (``extra='ignore'``)
so partial section evolution does not fail startup. Type errors and missing
required fields (e.g. ``mcp_tools[].name``) still fail fast with field paths.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

logger = logging.getLogger(__name__)

# Top-level keys consumed by braindrain/config.py or validated for drift detection.
KNOWN_TOP_LEVEL_KEYS = frozenset(
    {
        "version",
        "project_name",
        "modules",
        "mcp_tools",
        "workflows",
        "models",
        "embeddings",
        "observer",
        "memory_learning",
        "sessions",
        "wiki_brain",
        "lessons",
        "dreaming",
        "provider_context",
        "planning_auditor",
        "cost_tracking",
        "provenance",
        "complexity_router",
        "cache",
        "bundles",
        "agent_capabilities",
        "token_policy",
        "comms",
    }
)

EXCLUDED_TOP_LEVEL_KEYS = frozenset({"livingdash"})


class ConfigValidationError(ValueError):
    """Raised when hub_config.yaml fails schema validation."""

    def __init__(self, message: str, *, errors: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.errors = errors or []


def format_validation_error(exc: ValidationError) -> str:
    """Format Pydantic errors into actionable field paths."""
    parts: list[str] = []
    for err in exc.errors():
        loc = ".".join(str(part) for part in err.get("loc", ()))
        msg = err.get("msg", "invalid value")
        parts.append(f"{loc}: {msg}" if loc else msg)
    return "; ".join(parts)


class _ExtraIgnoreModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class ToolGateModule(_ExtraIgnoreModel):
    model_config = ConfigDict(extra="allow")

    enabled: bool = True
    rerank_on_search: bool = False
    rerank_provider: str = "none"
    rerank_model: str = "mixedbread-ai/mxbai-rerank-base-v2"
    rerank_top_k: int = 5


class OutputSandboxModule(_ExtraIgnoreModel):
    enabled: bool = True
    backend: str = "context_mode"
    enforce_hooks: bool = True


class WorkflowEngineModule(_ExtraIgnoreModel):
    enabled: bool = True
    use_model_tiers: bool = False


class ContextDatabaseModule(_ExtraIgnoreModel):
    enabled: bool = False


class EnvContextModule(_ExtraIgnoreModel):
    enabled: bool = True
    cache_path: str = "~/.braindrain/env_context.json"
    hot: bool = True
    description: str = ""


class ModulesConfig(_ExtraIgnoreModel):
    tool_gate: ToolGateModule = Field(default_factory=ToolGateModule)
    output_sandbox: OutputSandboxModule = Field(default_factory=OutputSandboxModule)
    workflow_engine: WorkflowEngineModule = Field(default_factory=WorkflowEngineModule)
    context_database: ContextDatabaseModule = Field(default_factory=ContextDatabaseModule)
    env_context: EnvContextModule = Field(default_factory=EnvContextModule)


class MCPToolEntry(_ExtraIgnoreModel):
    name: str
    command: str | None = None
    transport: str = "stdio"
    url: str | None = None
    hot: bool = False
    defer_loading: bool = True
    tags: list[str] = Field(default_factory=list)
    description: str = ""
    input_examples: list[dict[str, Any]] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    token_weight: str = "medium"
    roles: list[str] = Field(default_factory=list)
    bundles: list[str] = Field(default_factory=list)
    hot_tools: list[str] = Field(default_factory=list)


class WorkflowEntry(_ExtraIgnoreModel):
    name: str
    description: str = ""
    steps: list[Any] = Field(default_factory=list)
    executes_in: str = "sandbox"
    model: str = "tier_local"
    token_budget: int = 2000
    plan_before_run: bool = False
    input_examples: list[dict[str, Any]] = Field(default_factory=list)
    required_roles: list[str] = Field(default_factory=list)
    output_mode: str = "compact"
    options: dict[str, Any] = Field(default_factory=dict)


class ModelTierEntry(_ExtraIgnoreModel):
    provider: str = "ollama"
    model: str = ""
    api_base: str | None = None
    use_for: list[str] = Field(default_factory=list)
    cost_per_1k: float = 0.0
    cost_per_1k_input: float | None = None
    cost_per_1k_output: float | None = None
    max_tokens: int = 4096


class EmbeddingsRerankConfig(_ExtraIgnoreModel):
    provider: str = "none"
    model: str = ""


class EmbeddingsProviderEntry(_ExtraIgnoreModel):
    name: str
    kind: str = "openai_compat"
    base_url: str = ""
    api_key_env: str = ""
    model: str = ""
    priority: int = 0


class EmbeddingsConfig(_ExtraIgnoreModel):
    default_provider: str = "lmstudio_local"
    default_model: str = ""
    rerank: EmbeddingsRerankConfig = Field(default_factory=EmbeddingsRerankConfig)
    providers: list[EmbeddingsProviderEntry] = Field(default_factory=list)


class ObserverConfig(_ExtraIgnoreModel):
    enabled: bool = True
    storage_path: str = "~/.braindrain/events.db"
    ring_buffer_max: int = 10000
    wrap_all_tools: bool = True
    hash_args: bool = True


class MemoryPromotionConfig(_ExtraIgnoreModel):
    reject_secrets: bool = True
    reject_transient_state: bool = True
    require_repeat_observation: int = 1
    require_grounded_evidence: bool = False
    min_confidence: float = 0.0


class MemoryLearningConfig(_ExtraIgnoreModel):
    promotion: MemoryPromotionConfig = Field(default_factory=MemoryPromotionConfig)


class SessionsConfig(_ExtraIgnoreModel):
    storage_path: str = "~/.braindrain/sessions.db"
    inactivity_timeout_minutes: int = 30


class WikiBrainRecallConfig(_ExtraIgnoreModel):
    similarity_weight: float = 0.5
    recency_weight: float = 0.3
    importance_weight: float = 0.2
    recency_half_life_days: float = 30.0


class WikiBrainForgettingConfig(_ExtraIgnoreModel):
    decay_half_life_days: float = 90.0
    prune_threshold: float = 0.05
    consolidation_similarity: float = 0.92


class WikiBrainGatingConfig(_ExtraIgnoreModel):
    salience_threshold: float = 0.0


class WikiBrainBoundsConfig(_ExtraIgnoreModel):
    max_active_records: int = 0


class WikiBrainAssociativeGraphConfig(_ExtraIgnoreModel):
    enabled: bool = False
    similarity_threshold: float = 0.8


class WikiBrainHybridRetrievalConfig(_ExtraIgnoreModel):
    enabled: bool = False
    dense_weight: float = 0.2


class WikiBrainConfig(_ExtraIgnoreModel):
    storage_path: str = "~/.braindrain/wiki-brain/brain.db"
    recall: WikiBrainRecallConfig = Field(default_factory=WikiBrainRecallConfig)
    forgetting: WikiBrainForgettingConfig = Field(default_factory=WikiBrainForgettingConfig)
    gating: WikiBrainGatingConfig = Field(default_factory=WikiBrainGatingConfig)
    bounds: WikiBrainBoundsConfig = Field(default_factory=WikiBrainBoundsConfig)
    associative_graph: WikiBrainAssociativeGraphConfig = Field(
        default_factory=WikiBrainAssociativeGraphConfig
    )
    hybrid_retrieval: WikiBrainHybridRetrievalConfig = Field(
        default_factory=WikiBrainHybridRetrievalConfig
    )


class LessonsPromotionConfig(_ExtraIgnoreModel):
    require_grounded_evidence: bool = True
    min_confidence: float = 0.0


class LessonsConfig(_ExtraIgnoreModel):
    promotion: LessonsPromotionConfig = Field(default_factory=LessonsPromotionConfig)


class DreamWeights(_ExtraIgnoreModel):
    frequency: float = 0.24
    relevance: float = 0.30
    query_diversity: float = 0.15
    recency: float = 0.15
    consolidation: float = 0.10
    conceptual_richness: float = 0.06


class DreamStorageConfig(_ExtraIgnoreModel):
    base_dir: str = "~/.braindrain/dreaming"


class MacosHostIdleTrigger(_ExtraIgnoreModel):
    enabled: bool = False
    mode: str = "full"
    idle_threshold_seconds: int = 300
    poll_interval_seconds: int = 120
    bypass_session_quiet: bool = True
    cooldown_minutes: int = 60


class DreamTriggersConfig(_ExtraIgnoreModel):
    macos_host_idle: MacosHostIdleTrigger = Field(default_factory=MacosHostIdleTrigger)


class DreamingConfig(_ExtraIgnoreModel):
    policy_version: str = "memory-lessons-v1"
    quiet_minutes: int = 30
    lookback_hours: int = 72
    max_episode_scan: int = 50
    max_event_scan: int = 250
    max_session_scan: int = 20
    deep: dict[str, Any] = Field(default_factory=dict)
    storage: DreamStorageConfig = Field(default_factory=DreamStorageConfig)
    weights: DreamWeights = Field(default_factory=DreamWeights)
    triggers: DreamTriggersConfig = Field(default_factory=DreamTriggersConfig)


class ProviderContextConfig(_ExtraIgnoreModel):
    strategy: str = "provider-native-first"


class PlanningAuditorConfig(_ExtraIgnoreModel):
    overlap_jaccard_threshold: float = 0.55
    apply_overlap_relations: bool = False
    apply_goal_tags: bool = False
    goal_alignment_min_score: int = 40


class CostTrackingRates(_ExtraIgnoreModel):
    input_per_1m: float = 1.25
    output_per_1m: float = 6.0
    cache_read_per_1m: float = 0.25


class CostTrackingConfig(_ExtraIgnoreModel):
    enabled: bool = True
    log_file: str = "~/.braindrain/costs/session.jsonl"
    estimator: str = "chars"
    route_threshold_chars: int = 4096
    auto_route_output: bool = True
    rates: CostTrackingRates = Field(default_factory=CostTrackingRates)
    track_fields: list[str] = Field(default_factory=list)
    alert_threshold_usd_per_session: float = 0.50
    dashboard: bool = True


class ProvenanceChatFooter(_ExtraIgnoreModel):
    enabled: bool = True
    scope: str = "all_agents"


class ProvenancePlanMetadata(_ExtraIgnoreModel):
    enabled: bool = True


class ProvenanceSubagentTrace(_ExtraIgnoreModel):
    enabled: bool = True
    path: str = ".braindrain/plan-reports/model-trace.jsonl"


class ProvenanceConfig(_ExtraIgnoreModel):
    enabled: bool = True
    date_format: str = "%Y-%m-%d"
    chat_footer: ProvenanceChatFooter = Field(default_factory=ProvenanceChatFooter)
    plan_metadata: ProvenancePlanMetadata = Field(default_factory=ProvenancePlanMetadata)
    subagent_trace: ProvenanceSubagentTrace = Field(default_factory=ProvenanceSubagentTrace)


class HubConfigSchema(_ExtraIgnoreModel):
    version: str = "1.0"
    project_name: str = "braindrain"
    modules: ModulesConfig = Field(default_factory=ModulesConfig)
    mcp_tools: list[MCPToolEntry] = Field(default_factory=list)
    workflows: list[WorkflowEntry] = Field(default_factory=list)
    models: dict[str, ModelTierEntry] = Field(default_factory=dict)
    embeddings: EmbeddingsConfig = Field(default_factory=EmbeddingsConfig)
    observer: ObserverConfig = Field(default_factory=ObserverConfig)
    memory_learning: MemoryLearningConfig = Field(default_factory=MemoryLearningConfig)
    sessions: SessionsConfig = Field(default_factory=SessionsConfig)
    wiki_brain: WikiBrainConfig = Field(default_factory=WikiBrainConfig)
    lessons: LessonsConfig = Field(default_factory=LessonsConfig)
    dreaming: DreamingConfig = Field(default_factory=DreamingConfig)
    provider_context: ProviderContextConfig = Field(default_factory=ProviderContextConfig)
    planning_auditor: PlanningAuditorConfig = Field(default_factory=PlanningAuditorConfig)
    cost_tracking: CostTrackingConfig = Field(default_factory=CostTrackingConfig)
    provenance: ProvenanceConfig = Field(default_factory=ProvenanceConfig)
    complexity_router: dict[str, Any] = Field(default_factory=dict)
    cache: dict[str, Any] = Field(default_factory=dict)
    bundles: dict[str, Any] = Field(default_factory=dict)
    agent_capabilities: dict[str, Any] = Field(default_factory=dict)
    token_policy: dict[str, Any] = Field(default_factory=dict)
    comms: dict[str, Any] = Field(default_factory=dict)

    @field_validator("mcp_tools")
    @classmethod
    def _mcp_tools_not_none(cls, value: list[MCPToolEntry] | None) -> list[MCPToolEntry]:
        return value or []


def _collect_unknown_top_level_keys(raw: dict[str, Any]) -> list[str]:
    unknown = sorted(
        key for key in raw if key not in KNOWN_TOP_LEVEL_KEYS and key not in EXCLUDED_TOP_LEVEL_KEYS
    )
    return unknown


def validate_hub_config(raw: dict[str, Any] | None) -> tuple[HubConfigSchema, list[str]]:
    """Validate raw YAML dict; warn on unknown top-level keys; fail on type errors."""
    if raw is None:
        raw = {}

    if not isinstance(raw, dict):
        raise ConfigValidationError(
            "hub_config.yaml root must be a mapping",
            errors=[{"loc": (), "msg": "expected object"}],
        )

    warnings: list[str] = []
    for key in _collect_unknown_top_level_keys(raw):
        message = (
            f"Unknown top-level config key '{key}' ignored "
            "(forward-compat policy; see braindrain.config_schema)"
        )
        warnings.append(message)
        logger.warning(message)

    if "livingdash" in raw:
        message = "Top-level 'livingdash' block is ignored (superseded by MCP Apps dashboard plan)"
        warnings.append(message)
        logger.warning(message)

    filtered = {key: value for key, value in raw.items() if key in KNOWN_TOP_LEVEL_KEYS}

    try:
        validated = HubConfigSchema.model_validate(filtered)
    except ValidationError as exc:
        raise ConfigValidationError(
            f"Invalid hub_config.yaml: {format_validation_error(exc)}",
            errors=list(exc.errors()),
        ) from exc

    return validated, warnings


def validated_to_raw_dict(validated: HubConfigSchema) -> dict[str, Any]:
    """Convert validated schema back to a plain dict for Config._parse_config."""
    return validated.model_dump(mode="python")
