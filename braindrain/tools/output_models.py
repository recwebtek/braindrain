"""Structured output models and schemas for high-value MCP tools."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _BaseOut(BaseModel):
    model_config = ConfigDict(extra="allow")


class SearchToolItem(_BaseOut):
    name: str
    description: str
    tags: list[str] = Field(default_factory=list)
    defer_loading: bool | None = None
    roles: list[str] | None = None
    bundles: list[str] | None = None
    score: float | None = None


class SearchToolsOutput(_BaseOut):
    tools: list[SearchToolItem]
    total_available: int
    query: str


class TokenDashboardOutput(_BaseOut):
    started_at: int | float | None = None
    uptime_seconds: int | float | None = None
    tokens_in_raw_est: int | float | None = None
    tokens_in_actual_est: int | float | None = None
    tokens_saved_est: int | float | None = None
    saved_pct_est: int | float | None = None
    cache_hits: int | None = None
    cost_avoided_usd: int | float | None = None


class EnvContextOutput(_BaseOut):
    cached: bool
    probe_timestamp: str
    agents_md_block: str
    summary: dict


class SessionSummaryOutput(_BaseOut):
    status: str | None = None
    session_id: str | None = None
    retrieval_hint: str | None = None
    compact_package: dict | None = None


class WorkflowDescriptor(_BaseOut):
    name: str
    description: str | None = None
    token_budget: int | None = None
    steps: list[str] | None = None


class ListWorkflowsOutput(_BaseOut):
    workflows: list[WorkflowDescriptor] | None = None


class RegistryStats(_BaseOut):
    total_tools: int
    hot_tools: int
    deferred_tools: int
    search_index_ready: bool


class TokenStatsOutput(_BaseOut):
    session: dict
    registry: RegistryStats
    project: str | None = None
    version: str | None = None


class SearchIndexOutput(_BaseOut):
    query: str | None = None
    limit: int | None = None
    results: list[dict] | None = None
    rerank: dict | None = None
    error: str | None = None


class RouteOutputModel(_BaseOut):
    routed: bool
    source: str
    handle: str | None = None
    index_id: str | None = None
    bytes_raw: int | None = None
    preview: str | None = None
    retrieval_hint: str | None = None
    text: str | None = None
    text_preview: str | None = None
    error: str | None = None
    suggested_queries: list[str] | None = None
    context_mode: dict | None = None
    next_steps: dict | None = None


class AvailableToolItem(_BaseOut):
    name: str
    description: str
    tags: list[str] = Field(default_factory=list)


class GetAvailableToolsOutput(_BaseOut):
    hot_tools: list[AvailableToolItem]
    hot_count: int
    deferred_tools: list[AvailableToolItem]
    deferred_count: int


class PrimeWorkspaceOutput(_BaseOut):
    ok: bool
    target: str | None = None
    dry_run: bool | None = None
    bundle: str | None = None
    next_steps: list[str] | None = None


def schema_for(model: type[BaseModel]) -> dict:
    """Return JSON Schema with inline refs for MCP output_schema."""
    schema = model.model_json_schema(ref_template="#/$defs/{model}")
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", **schema}
