"""Output routing to reduce token usage.

If output is large, index it into context-mode (FTS5) and return a compact
response containing a handle and suggested search queries.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class RoutedOutput:
    routed: bool
    source: str
    handle: str
    preview: str
    suggested_queries: list[str]
    bytes_raw: int


def _stable_handle(source: str, content: str) -> str:
    h = hashlib.sha256()
    h.update(source.encode("utf-8", errors="ignore"))
    h.update(b"\n")
    h.update(content.encode("utf-8", errors="ignore"))
    return h.hexdigest()[:16]


def _build_markdown(source: str, handle: str, content: str) -> str:
    # Keep content in a fenced block so ctx_index preserves structure.
    return (
        f"# BRAINDRAIN_OUTPUT\n\n"
        f"- source: `{source}`\n"
        f"- handle: `{handle}`\n\n"
        f"## Raw\n\n"
        f"```text\n{content}\n```\n"
    )


def _preview(content: str, max_chars: int = 400) -> str:
    s = content.strip()
    if len(s) <= max_chars:
        return s
    return s[: max_chars - 3] + "..."


def should_route(content: str, *, min_chars: int = 5000) -> bool:
    return len(content) >= min_chars


def build_routed_output(
    *,
    source: str,
    content: str,
    intent: Optional[str] = None,
) -> tuple[RoutedOutput, str]:
    """
    Returns (routed_output, markdown_to_index).
    The caller is responsible for indexing markdown_to_index via context-mode.
    """
    handle = _stable_handle(source, content)
    md = _build_markdown(source, handle, content)
    base_queries = [f"handle:{handle}", handle, source]
    if intent:
        base_queries.insert(0, intent)

    ro = RoutedOutput(
        routed=True,
        source=source,
        handle=handle,
        preview=_preview(content),
        suggested_queries=base_queries,
        bytes_raw=len(content.encode("utf-8", errors="ignore")),
    )
    return ro, md

