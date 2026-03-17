"""Local-first embeddings provider router (Phase 3 scaffold).

Goal: always have a working local embedding backend, but opportunistically use
free/cheap cloud quotas (Groq, Hugging Face, etc.) when available.

This module is intentionally lightweight and does not force any provider choice
into the MCP surface yet — it will be wired into semantic search tools later.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    kind: str  # local_ollama | local_lmstudio | openai_compat | hf_inference | groq_compat
    model: str
    base_url: Optional[str] = None
    api_key_env: Optional[str] = None
    priority: int = 100  # lower wins
    enabled: bool = True

    # Optional quota knobs (best-effort, enforced by caller increments)
    daily_quota_requests: Optional[int] = None


@dataclass
class ProviderState:
    consecutive_failures: int = 0
    last_failure_ts: Optional[float] = None
    requests_today: int = 0
    day_epoch: int = field(default_factory=lambda: int(time.time() // 86400))

    def _roll_day(self) -> None:
        today = int(time.time() // 86400)
        if today != self.day_epoch:
            self.day_epoch = today
            self.requests_today = 0

    def can_use(self, cfg: ProviderConfig) -> bool:
        self._roll_day()
        if cfg.daily_quota_requests is None:
            return True
        return self.requests_today < cfg.daily_quota_requests

    def note_request(self) -> None:
        self._roll_day()
        self.requests_today += 1

    def note_success(self) -> None:
        self.consecutive_failures = 0
        self.last_failure_ts = None

    def note_failure(self) -> None:
        self.consecutive_failures += 1
        self.last_failure_ts = time.time()


class EmbeddingsRouter:
    def __init__(self, providers: list[ProviderConfig], *, cooldown_seconds: int = 60) -> None:
        self.providers = sorted([p for p in providers if p.enabled], key=lambda p: p.priority)
        self.cooldown_seconds = cooldown_seconds
        self._state: dict[str, ProviderState] = {p.name: ProviderState() for p in self.providers}

    def pick(self) -> Optional[ProviderConfig]:
        now = time.time()
        for p in self.providers:
            st = self._state[p.name]

            # Require key for cloud providers if configured that way.
            if p.api_key_env:
                if not os.environ.get(p.api_key_env):
                    continue

            # Backoff after repeated failures.
            if st.consecutive_failures >= 3 and st.last_failure_ts is not None:
                if (now - st.last_failure_ts) < self.cooldown_seconds:
                    continue

            if not st.can_use(p):
                continue

            return p
        return None

    def note_request(self, provider_name: str) -> None:
        if provider_name in self._state:
            self._state[provider_name].note_request()

    def note_success(self, provider_name: str) -> None:
        if provider_name in self._state:
            self._state[provider_name].note_success()

    def note_failure(self, provider_name: str) -> None:
        if provider_name in self._state:
            self._state[provider_name].note_failure()

    def snapshot(self) -> dict:
        return {
            "providers": [
                {
                    "name": p.name,
                    "kind": p.kind,
                    "model": p.model,
                    "base_url": p.base_url,
                    "priority": p.priority,
                    "enabled": p.enabled,
                    "daily_quota_requests": p.daily_quota_requests,
                    "state": {
                        "consecutive_failures": self._state[p.name].consecutive_failures,
                        "last_failure_ts": self._state[p.name].last_failure_ts,
                        "requests_today": self._state[p.name].requests_today,
                    },
                }
                for p in self.providers
            ]
        }

