"""Local-first embeddings client (LM Studio, Ollama, OpenAI-compatible cloud)."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Optional

from braindrain.embeddings_router import EmbeddingsRouter, ProviderConfig


def _resolve_env(value: str, *, default: str = "") -> str:
    if not value or "${" not in value:
        return value or default
    # Minimal ${VAR:-default} support used in hub_config.yaml
    if value.startswith("${") and value.endswith("}"):
        inner = value[2:-1]
        if ":-" in inner:
            var, fallback = inner.split(":-", 1)
            return os.environ.get(var, fallback)
        return os.environ.get(inner, default)
    return value


def providers_from_config(embeddings_cfg: dict) -> list[ProviderConfig]:
    out: list[ProviderConfig] = []
    for raw in embeddings_cfg.get("providers") or []:
        if not isinstance(raw, dict):
            continue
        out.append(
            ProviderConfig(
                name=str(raw.get("name", "")),
                kind=str(raw.get("kind", "openai_compat")),
                model=str(raw.get("model", "")),
                base_url=_resolve_env(str(raw.get("base_url") or "")),
                api_key_env=raw.get("api_key_env"),
                priority=int(raw.get("priority", 100)),
                enabled=bool(raw.get("enabled", True)),
            )
        )
    return [p for p in out if p.name and p.model]


def pick_provider(
    embeddings_cfg: dict,
    *,
    preferred: str | None = None,
) -> Optional[ProviderConfig]:
    providers = providers_from_config(embeddings_cfg)
    if preferred:
        for p in providers:
            if p.name == preferred:
                return p
    default_name = str(embeddings_cfg.get("default_provider") or "").strip()
    if default_name:
        for p in providers:
            if p.name == default_name:
                return p
    router = EmbeddingsRouter(providers)
    return router.pick()


def _http_json(
    *,
    url: str,
    payload: dict,
    headers: dict[str, str],
    timeout: float = 60.0,
) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def embed_texts(
    texts: list[str],
    *,
    embeddings_cfg: dict,
    provider_name: str | None = None,
) -> dict[str, Any]:
    """
    Embed texts using configured providers (local-first by priority).

    No-op failure returns {"ok": False, "error": ...} — callers can fall back to FTS/BM25.
    """
    if not texts:
        return {"ok": True, "embeddings": [], "provider": None}

    provider = pick_provider(embeddings_cfg, preferred=provider_name)
    if provider is None:
        return {"ok": False, "error": "no_embedding_provider_available"}

    api_key = ""
    if provider.api_key_env:
        api_key = os.environ.get(str(provider.api_key_env), "")

    try:
        if provider.kind == "ollama":
            base = (provider.base_url or "http://localhost:11434").rstrip("/")
            vectors: list[list[float]] = []
            for text in texts:
                raw = _http_json(
                    url=f"{base}/api/embed",
                    payload={"model": provider.model, "input": text},
                    headers={"Content-Type": "application/json"},
                )
                row = raw.get("embeddings")
                if isinstance(row, list) and row and isinstance(row[0], list):
                    vectors.append(row[0])
                elif isinstance(row, list) and row and isinstance(row[0], (int, float)):
                    vectors.append(row)  # type: ignore[arg-type]
                else:
                    return {"ok": False, "error": "ollama_embed_unexpected_shape", "provider": provider.name}
            return {
                "ok": True,
                "provider": provider.name,
                "model": provider.model,
                "kind": provider.kind,
                "embeddings": vectors,
            }

        # openai_compat (LM Studio, Mixedbread, gateways)
        base = (provider.base_url or "http://localhost:1234/v1").rstrip("/")
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        raw = _http_json(
            url=f"{base}/embeddings",
            payload={"model": provider.model, "input": texts},
            headers=headers,
        )
        data = raw.get("data") if isinstance(raw, dict) else None
        if not isinstance(data, list):
            return {"ok": False, "error": "embeddings_unexpected_response", "provider": provider.name}
        vectors = []
        for row in sorted(data, key=lambda r: r.get("index", 0) if isinstance(r, dict) else 0):
            if isinstance(row, dict) and isinstance(row.get("embedding"), list):
                vectors.append(row["embedding"])
        if len(vectors) != len(texts):
            return {"ok": False, "error": "embedding_count_mismatch", "provider": provider.name}
        return {
            "ok": True,
            "provider": provider.name,
            "model": provider.model,
            "kind": provider.kind,
            "embeddings": vectors,
        }
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:500]
        return {"ok": False, "error": f"embed HTTP {e.code}: {detail}", "provider": provider.name}
    except Exception as e:  # pragma: no cover
        return {"ok": False, "error": str(e), "provider": provider.name}
