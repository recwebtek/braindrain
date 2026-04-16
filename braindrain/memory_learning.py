"""Memory and learning guardrails for project-comms usage."""

from __future__ import annotations

import re
from typing import Any


_SECRET_PATTERNS = [
    re.compile(r"(?i)\b(token|apikey|api_key|secret|password)\b\s*[:=]\s*[\w\-]{8,}"),
    re.compile(r"(?i)bearer\s+[a-z0-9\-_\.=]{8,}"),
]


def looks_secret(text: str) -> bool:
    return any(p.search(text) for p in _SECRET_PATTERNS)


def sanitize_for_comms(text: str, *, max_chars: int = 1200) -> str:
    out = text.replace("\r", " ").replace("\t", " ")
    out = re.sub(r"\s+", " ", out).strip()
    if looks_secret(out):
        return "[redacted: potential secret detected]"
    if len(out) > max_chars:
        return out[: max_chars - 20] + " ...[truncated]"
    return out


def _contains_transient_state(candidate: str, policy: dict[str, Any]) -> bool:
    transient_markers = tuple(
        policy.get(
            "transient_markers",
            ("today", "just now", "temporary", "debug only"),
        )
    )
    text = candidate.lower()
    return any(marker in text for marker in transient_markers)


def can_promote_memory(candidate: str, policy: dict[str, Any]) -> dict[str, Any]:
    if not candidate.strip():
        return {"ok": False, "reason": "empty"}
    if policy.get("reject_secrets", True) and looks_secret(candidate):
        return {"ok": False, "reason": "secret_detected"}
    if policy.get("reject_transient_state", True) and _contains_transient_state(candidate, policy):
        return {"ok": False, "reason": "transient_state"}

    require_repeat = int(policy.get("require_repeat_observation", 1) or 1)
    observation_count = int(policy.get("observation_count", require_repeat) or 0)
    if observation_count < require_repeat:
        return {
            "ok": False,
            "reason": "insufficient_repetition",
            "required": require_repeat,
            "observed": observation_count,
        }

    if policy.get("require_grounded_evidence", False):
        evidence_refs = policy.get("evidence_refs") or []
        if not evidence_refs:
            return {"ok": False, "reason": "missing_grounded_evidence"}

    min_confidence = float(policy.get("min_confidence", 0.0) or 0.0)
    confidence = float(policy.get("confidence", 1.0) or 0.0)
    if confidence < min_confidence:
        return {
            "ok": False,
            "reason": "low_confidence",
            "required": min_confidence,
            "observed": confidence,
        }

    return {
        "ok": True,
        "memory_class": policy.get("memory_class", "semantic"),
        "repeat_observation_threshold": require_repeat,
        "grounded": bool(policy.get("evidence_refs")),
        "confidence": confidence,
    }


def evaluate_lesson_candidate(
    *,
    problem: str,
    action: str,
    outcome: str,
    local_critique: str = "",
    global_reflection: str = "",
    evidence_refs: list[str] | None = None,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    policy = policy or {}
    content = " ".join(
        part
        for part in [
            problem.strip(),
            action.strip(),
            outcome.strip(),
            local_critique.strip(),
            global_reflection.strip(),
        ]
        if part
    )
    verdict = can_promote_memory(
        content,
        {
            **policy,
            "require_grounded_evidence": policy.get("require_grounded_evidence", True),
            "evidence_refs": evidence_refs or [],
            "memory_class": "lesson",
            "confidence": policy.get(
                "confidence",
                0.7 if (local_critique or global_reflection) else 0.5,
            ),
        },
    )
    has_critique = bool(local_critique.strip() or global_reflection.strip())
    has_outcome = bool(outcome.strip())
    if verdict.get("ok") and not has_outcome:
        return {"ok": False, "reason": "missing_outcome"}
    if verdict.get("ok") and not has_critique:
        return {"ok": False, "reason": "missing_critique"}
    return {
        **verdict,
        "candidate_type": "lesson",
        "has_outcome": has_outcome,
        "has_critique": has_critique,
        "sanitized_preview": sanitize_for_comms(content, max_chars=240),
    }


def build_learning_index_entry(
    *,
    transcript_id: str,
    path: str,
    mtime: float,
    summary: str,
) -> dict[str, Any]:
    return {
        "transcript_id": transcript_id,
        "path": path,
        "mtime": mtime,
        "summary": sanitize_for_comms(summary, max_chars=500),
    }
