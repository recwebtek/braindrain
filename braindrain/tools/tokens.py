"""Token/search/output tool implementations extracted from server.py."""

from __future__ import annotations

from braindrain.context_mode_client import MCPProtocolError
from braindrain.output_router import build_routed_output
from braindrain.rerank import maybe_rerank_search_results


async def search_tools_impl(registry, query: str = "", top_k: int = 5) -> dict:
    results = await registry.search_async(query or "", top_k)
    return {"tools": results, "total_available": registry.count(), "query": query}


async def get_token_stats_impl(registry, telemetry, config) -> dict:
    stats = registry.get_stats()
    return {
        "session": telemetry.snapshot(),
        "registry": stats,
        "project": config.get("project_name"),
        "version": config.get("version"),
    }


async def get_available_tools_impl(config) -> dict:
    hot_tools = []
    deferred_tools = []
    for tool in config.mcp_tools:
        tool_info = {"name": tool.name, "description": tool.description, "tags": tool.tags}
        if tool.hot:
            hot_tools.append(tool_info)
        else:
            deferred_tools.append(tool_info)
    return {
        "hot_tools": hot_tools,
        "hot_count": len(hot_tools),
        "deferred_tools": deferred_tools,
        "deferred_count": len(deferred_tools),
    }


async def route_output_impl(
    get_context_mode_client,
    should_route_output,
    text: str,
    source: str = "braindrain",
    intent: str | None = None,
    min_chars: int = 5000,
    force_index: bool = False,
    force_inline: bool = False,
) -> dict:
    if not force_index and not should_route_output(
        text, min_chars=min_chars, force_inline=force_inline
    ):
        return {
            "routed": False,
            "source": source,
            "bytes_raw": len(text.encode("utf-8", errors="ignore")),
            "text": text,
        }
    client = get_context_mode_client()
    if client is None:
        return {
            "routed": False,
            "error": "context_mode is not configured; cannot index",
            "source": source,
            "bytes_raw": len(text.encode("utf-8", errors="ignore")),
            "text_preview": text[:400],
        }
    routed, md = build_routed_output(source=source, content=text, intent=intent)
    try:
        index_result = await client.index_markdown(content_md=md, source=source, intent=intent)
    except MCPProtocolError as e:
        return {
            "routed": False,
            "error": f"context-mode indexing failed: {e}",
            "source": source,
            "bytes_raw": routed.bytes_raw,
            "text_preview": routed.preview,
        }
    return {
        "routed": True,
        "source": source,
        "handle": routed.handle,
        "index_id": routed.handle,
        "bytes_raw": routed.bytes_raw,
        "preview": routed.preview,
        "suggested_queries": routed.suggested_queries,
        "retrieval_hint": f"Call search_index with query handle:{routed.handle} or a suggested_queries entry.",
        "context_mode": {"indexed_via": "ctx_index", "index_result": index_result},
        "next_steps": {
            "use_ctx_search": True,
            "examples": [
                {"tool": "search_index", "query": q} for q in routed.suggested_queries[:3]
            ],
        },
    }


async def search_index_impl(
    get_context_mode_client,
    config,
    query: str,
    limit: int = 5,
    rerank: bool | None = None,
    fallback_search=None,
) -> dict:
    client = get_context_mode_client()
    if client is None:
        if fallback_search is not None:
            fallback_results = fallback_search(query=query, limit=limit)
            return {
                "query": query,
                "limit": limit,
                "results": fallback_results,
                "rerank": {"requested": False, "applied": False},
                "fallback": "wiki_brain_fts",
            }
        return {"error": "context_mode is not configured; cannot search"}
    try:
        results = await client.search(query=query, limit=limit)
        modules = config.get("modules", {}) or {}
        tool_gate = modules.get("tool_gate", {}) if isinstance(modules, dict) else {}
        embeddings_cfg = (
            getattr(config.data, "embeddings", None) or config.get("embeddings", {}) or {}
        )
        do_rerank = rerank if rerank is not None else bool(tool_gate.get("rerank_on_search", False))
        rerank_meta: dict = {"requested": bool(do_rerank)}
        if do_rerank:
            results, rerank_meta = maybe_rerank_search_results(
                query=query,
                results=results,
                embeddings_cfg=embeddings_cfg if isinstance(embeddings_cfg, dict) else {},
                tool_gate_cfg=tool_gate if isinstance(tool_gate, dict) else {},
                limit=limit,
            )
        return {"query": query, "limit": limit, "results": results, "rerank": rerank_meta}
    except MCPProtocolError as e:
        if fallback_search is not None:
            fallback_results = fallback_search(query=query, limit=limit)
            return {
                "query": query,
                "limit": limit,
                "results": fallback_results,
                "rerank": {"requested": False, "applied": False},
                "fallback": "wiki_brain_fts",
                "warning": f"context-mode unavailable: {e}",
            }
        return {"error": f"context-mode search failed: {e}"}
