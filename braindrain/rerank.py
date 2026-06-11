"""Optional reranking for search_index (offline lexical or cloud APIs)."""

from __future__ import annotations

import json
import math
import os
import re
import urllib.error
import urllib.request
from typing import Any

_TOKEN_RE = re.compile(r"[a-z0-9_]+", re.I)


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _provider_by_name(embeddings_cfg: dict, name: str) -> dict | None:
    for provider in embeddings_cfg.get("providers") or []:
        if isinstance(provider, dict) and provider.get("name") == name:
            return provider
    return None


def _resolve_rerank_provider(embeddings_cfg: dict, tool_gate_cfg: dict) -> str:
    """Provider id: none | lexical | mixedbread | auto."""
    explicit = (
        str(
            tool_gate_cfg.get("rerank_provider")
            or embeddings_cfg.get("rerank", {}).get("provider")
            or "none"
        )
        .strip()
        .lower()
    )
    return explicit or "none"


def _extract_documents(results: Any) -> tuple[list[str], list[Any]]:
    """
    Normalize context-mode / FTS payloads into plain document strings.

    Returns (documents, original_items) where len(documents) == len(original_items).
    """
    items: list[Any] = []

    if isinstance(results, dict):
        for key in ("results", "chunks", "matches", "hits", "data"):
            candidate = results.get(key)
            if isinstance(candidate, list):
                items = candidate
                break
        if not items and "content" in results:
            items = [results]
    elif isinstance(results, list):
        items = results

    documents: list[str] = []
    originals: list[Any] = []

    for item in items:
        if isinstance(item, str):
            documents.append(item)
            originals.append(item)
            continue
        if not isinstance(item, dict):
            text = str(item)
            documents.append(text)
            originals.append(item)
            continue

        text = (
            item.get("text")
            or item.get("content")
            or item.get("snippet")
            or item.get("body")
            or item.get("chunk")
        )
        if not text and isinstance(item.get("metadata"), dict):
            text = item["metadata"].get("text") or item["metadata"].get("content")
        if not text:
            text = json.dumps(item, ensure_ascii=False)[:4000]
        documents.append(str(text))
        originals.append(item)

    return documents, originals


def lexical_rerank(*, query: str, documents: list[str], top_k: int) -> dict[str, Any]:
    """Offline rerank using token overlap (no API keys, no external deps)."""
    if not documents:
        return {"ok": True, "ranked_indices": [], "scores": [], "provider": "lexical"}

    q_tokens = _tokenize(query)
    if not q_tokens:
        return {
            "ok": True,
            "ranked_indices": list(range(min(top_k, len(documents)))),
            "scores": [0.0] * min(top_k, len(documents)),
            "provider": "lexical",
        }

    q_set = set(q_tokens)
    scored: list[tuple[float, int]] = []
    for i, doc in enumerate(documents):
        d_tokens = _tokenize(doc)
        if not d_tokens:
            scored.append((0.0, i))
            continue
        d_set = set(d_tokens)
        overlap = len(q_set & d_set)
        # Light length norm so long boilerplate does not dominate
        score = overlap / math.sqrt(len(d_set))
        scored.append((score, i))

    scored.sort(key=lambda t: (-t[0], t[1]))
    top = scored[:top_k]
    return {
        "ok": True,
        "ranked_indices": [i for _, i in top],
        "scores": [s for s, _ in top],
        "provider": "lexical",
    }


def api_rerank_documents(
    *,
    query: str,
    documents: list[str],
    api_key: str,
    base_url: str,
    model: str,
    top_k: int,
    timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    """Call OpenAI-compatible /reranking (Mixedbread and similar gateways)."""
    if not documents:
        return {"ok": True, "ranked_indices": [], "scores": []}

    url = base_url.rstrip("/") + "/reranking"
    payload = {
        "model": model,
        "query": query,
        "input": documents,
        "top_k": min(top_k, len(documents)),
    }
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    req = urllib.request.Request(url, data=body, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:500]
        return {"ok": False, "error": f"rerank HTTP {e.code}: {detail}"}
    except Exception as e:  # pragma: no cover
        return {"ok": False, "error": str(e)}

    ranked: list[dict[str, Any]] = []
    data = raw.get("data") if isinstance(raw, dict) else None
    if isinstance(data, list):
        for row in data:
            if not isinstance(row, dict):
                continue
            idx = row.get("index")
            if idx is None:
                continue
            ranked.append({"index": int(idx), "score": row.get("score")})
    else:
        alt = raw.get("results") if isinstance(raw, dict) else None
        if isinstance(alt, list):
            for row in alt:
                if isinstance(row, dict) and "index" in row:
                    ranked.append(
                        {
                            "index": int(row["index"]),
                            "score": row.get("relevance_score", row.get("score")),
                        }
                    )

    ranked.sort(key=lambda r: (-(r.get("score") or 0), r["index"]))
    return {
        "ok": True,
        "ranked_indices": [r["index"] for r in ranked[:top_k]],
        "scores": [r.get("score") for r in ranked[:top_k]],
        "model": model,
        "provider": "api",
    }


def _mixedbread_rerank(
    *,
    query: str,
    documents: list[str],
    embeddings_cfg: dict,
    tool_gate_cfg: dict,
    top_k: int,
) -> dict[str, Any]:
    provider = _provider_by_name(embeddings_cfg, "mixedbread")
    if not provider:
        return {"ok": False, "error": "mixedbread_provider_missing"}

    key_env = provider.get("api_key_env") or "MIXEDBREAD_API_KEY"
    api_key = os.environ.get(str(key_env), "")
    if not api_key:
        return {"ok": False, "error": "api_key_missing"}

    model = str(
        tool_gate_cfg.get("rerank_model")
        or embeddings_cfg.get("rerank", {}).get("model")
        or "mixedbread-ai/mxbai-rerank-base-v2"
    )
    base_url = str(provider.get("base_url") or "https://api.mixedbread.ai/v1")
    if "${" in base_url:
        base_url = os.environ.get("MIXEDBREAD_BASE_URL", "https://api.mixedbread.ai/v1")

    out = api_rerank_documents(
        query=query,
        documents=documents,
        api_key=api_key,
        base_url=base_url,
        model=model,
        top_k=top_k,
    )
    if out.get("ok"):
        out["provider"] = "mixedbread"
    return out


def _apply_ranking(
    *,
    results: Any,
    originals: list[Any],
    rerank_out: dict[str, Any],
) -> Any:
    indices = rerank_out.get("ranked_indices") or []
    reordered = [originals[i] for i in indices if 0 <= i < len(originals)]
    if isinstance(results, dict) and isinstance(results.get("results"), list):
        out = dict(results)
        out["results"] = reordered
        return out
    if isinstance(results, list):
        return reordered
    return reordered or results


def maybe_rerank_search_results(
    *,
    query: str,
    results: Any,
    embeddings_cfg: dict,
    tool_gate_cfg: dict,
    limit: int,
) -> tuple[Any, dict[str, Any]]:
    """
    Optionally rerank search hits.

    Default (`rerank_on_search: false`): no-op — search_index uses context-mode FTS only.
    Providers:
      - none: skip
      - lexical: offline token overlap (no API)
      - mixedbread: cloud rerank API (optional)
      - auto: mixedbread when API key present, else lexical
    """
    meta: dict[str, Any] = {"applied": False, "skipped_reason": None}
    if not bool(tool_gate_cfg.get("rerank_on_search", False)):
        meta["skipped_reason"] = "rerank_on_search_disabled"
        return results, meta

    provider_id = _resolve_rerank_provider(embeddings_cfg, tool_gate_cfg)
    if provider_id == "none":
        meta["skipped_reason"] = "rerank_provider_none"
        return results, meta

    documents, originals = _extract_documents(results)
    if len(documents) < 2:
        meta["skipped_reason"] = "insufficient_documents"
        return results, meta

    top_k = int(tool_gate_cfg.get("rerank_top_k") or limit)

    if provider_id == "auto":
        cloud = _mixedbread_rerank(
            query=query,
            documents=documents,
            embeddings_cfg=embeddings_cfg,
            tool_gate_cfg=tool_gate_cfg,
            top_k=top_k,
        )
        rerank_out = (
            cloud
            if cloud.get("ok")
            else lexical_rerank(query=query, documents=documents, top_k=top_k)
        )
        if not cloud.get("ok"):
            meta["fallback"] = cloud.get("error")
    elif provider_id == "mixedbread":
        rerank_out = _mixedbread_rerank(
            query=query,
            documents=documents,
            embeddings_cfg=embeddings_cfg,
            tool_gate_cfg=tool_gate_cfg,
            top_k=top_k,
        )
    elif provider_id == "lexical":
        rerank_out = lexical_rerank(query=query, documents=documents, top_k=top_k)
    else:
        meta["skipped_reason"] = f"unknown_rerank_provider:{provider_id}"
        return results, meta

    if not rerank_out.get("ok"):
        meta["skipped_reason"] = "rerank_failed"
        meta["error"] = rerank_out.get("error")
        return results, meta

    reordered = _apply_ranking(results=results, originals=originals, rerank_out=rerank_out)
    meta.update(
        {
            "applied": True,
            "provider": rerank_out.get("provider"),
            "model": rerank_out.get("model"),
            "ranked_indices": rerank_out.get("ranked_indices"),
            "scores": rerank_out.get("scores"),
            "document_count": len(documents),
        }
    )
    return reordered, meta


# Back-compat alias used in tests
rerank_documents = api_rerank_documents
