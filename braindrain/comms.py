"""Provider-agnostic communication contract and policy helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CommsEnvelope:
    provider: str
    channel: str
    message: str
    intent: str
    idempotency_key: str
    metadata: dict[str, Any]


def is_blocked_intent(intent: str, policy: dict[str, Any]) -> bool:
    blocked = set(policy.get("blocked_intents") or [])
    return intent.strip().lower() in blocked


def requires_escalation(intent: str, policy: dict[str, Any]) -> bool:
    escalation = set(policy.get("escalation_only_intents") or [])
    return intent.strip().lower() in escalation


def is_allowed_intent(intent: str, policy: dict[str, Any]) -> bool:
    allowed = set(policy.get("allowed_intents") or [])
    if not allowed:
        return True
    return intent.strip().lower() in allowed


def evaluate_intent(intent: str, policy: dict[str, Any]) -> dict[str, Any]:
    norm = intent.strip().lower()
    if is_blocked_intent(norm, policy):
        return {"allowed": False, "reason": "blocked_intent", "intent": norm}
    if requires_escalation(norm, policy):
        return {"allowed": True, "requires_escalation": True, "intent": norm}
    if not is_allowed_intent(norm, policy):
        return {"allowed": False, "reason": "not_in_allowlist", "intent": norm}
    return {"allowed": True, "requires_escalation": False, "intent": norm}
