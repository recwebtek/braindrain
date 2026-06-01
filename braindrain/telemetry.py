"""Token/cost telemetry for BRAINDRAIN.

MVP focus:
- Track estimated Claude/Anthropic token impact of routing large outputs through context-mode.
- Persist per-event JSONL to the configured log path.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Protocol


class TokenEstimator(Protocol):
    def estimate(self, text: str) -> int: ...


class CharDiv4Estimator:
    def estimate(self, text: str) -> int:
        if not text:
            return 0
        return max(1, len(text) // 4)


class TiktokenEstimator:
    def __init__(self, model: str = "cl100k_base") -> None:
        import tiktoken

        self._enc = tiktoken.get_encoding(model)

    def estimate(self, text: str) -> int:
        if not text:
            return 0
        return max(1, len(self._enc.encode(text)))


def build_estimator(cost_tracking: dict[str, Any]) -> TokenEstimator:
    name = str(cost_tracking.get("estimator", "chars") or "chars").lower()
    if name == "tiktoken":
        try:
            return TiktokenEstimator()
        except Exception:
            pass
    return CharDiv4Estimator()


def estimate_tokens(text: str, estimator: Optional[TokenEstimator] = None) -> int:
    est = estimator or CharDiv4Estimator()
    return est.estimate(text)


def estimate_claude_tokens(text: str) -> int:
    """Backward-compatible char/4 estimator."""
    return CharDiv4Estimator().estimate(text)


# Regex patterns for redaction (pre-compiled for performance)
# Paths: /Users/..., /Volumes/..., /home/..., /root/...
_PATH_RE = re.compile(r"(/Users/|/Volumes/|/home/|/root/)([^\s'\",;\n\t:]+)")
# API Keys: OpenAI/Anthropic (sk-), Groq (gsk_), HuggingFace (hf_), Google AI (AIza), AWS, Slack
_KEY_RE = re.compile(
    r"(sk-[a-zA-Z0-9-]{20,}|gsk_[a-zA-Z0-9]{20,}|hf_[a-zA-Z0-9]{20,}|AIza[a-zA-Z0-9_-]{35,}|A[KS]IA[A-Z0-9]{16}|xox[bparc]-[a-zA-Z0-9-]{12,})",
    re.IGNORECASE,
)
# Generic secrets in JSON or env format: "password": "...", PASSWORD=...
_GENERIC_SECRET_RE = re.compile(
    r"(['\"]?)([a-zA-Z0-9_-]*(?:password|secret|token|apikey|api_key|pass))\1(\s*[:=]\s*)(['\"]?)([^\s'\",;]+)\4",
    re.IGNORECASE,
)

# Machine-local debug reports (under .braindrain/, never committed).
_DEBUG_LOG_DIR = Path(".braindrain") / "logs"


@dataclass
class ToolAggregate:
    calls: int = 0
    tokens_in_raw_est: int = 0
    tokens_in_actual_est: int = 0

    @property
    def tokens_saved_est(self) -> int:
        return max(0, self.tokens_in_raw_est - self.tokens_in_actual_est)

    @property
    def saved_pct_est(self) -> float:
        if self.tokens_in_raw_est <= 0:
            return 0.0
        return (self.tokens_saved_est / self.tokens_in_raw_est) * 100.0


@dataclass
class TelemetrySession:
    log_file: Path
    started_at: float = field(default_factory=time.time)
    tools: dict[str, ToolAggregate] = field(default_factory=dict)
    cache_hits: int = 0
    cost_avoided_usd: float = 0.0
    estimator: TokenEstimator = field(default_factory=CharDiv4Estimator)
    rates: dict[str, float] = field(default_factory=dict)
    _env_context_hash: str | None = None
    module_attribution: dict[str, int] = field(
        default_factory=lambda: {
            "tool_gate": 0,
            "output_sandbox": 0,
            "workflow_engine": 0,
            "context_database": 0,
        }
    )

    def _ensure_parent(self) -> None:
        try:
            self.log_file.parent.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            fallback = _DEBUG_LOG_DIR / self.log_file.name
            if self.log_file != fallback:
                self.log_file = fallback
                self.log_file.parent.mkdir(parents=True, exist_ok=True)

    def sanitize(self, data: Any) -> Any:
        """Public entry point for recursive redaction of sensitive paths and API keys."""
        return self._sanitize_data(data)

    def _sanitize_data(self, data: Any) -> Any:
        """Recursive redaction of sensitive paths and API keys."""

        def _do_sanitize(val: Any) -> Any:
            if isinstance(val, str):
                # Optimization: skip regex overhead if the string has no characters indicating
                # a potential sensitive path or API key. ~3.5x speedup for clean strings.
                lower_val = val.lower()
                if (
                    "/" not in val
                    and "sk-" not in lower_val
                    and "akia" not in lower_val
                    and "asia" not in lower_val
                    and "xox" not in lower_val
                    and "gsk_" not in lower_val
                    and "hf_" not in lower_val
                    and "aiza" not in lower_val
                    and "password" not in lower_val
                    and "secret" not in lower_val
                    and "token" not in lower_val
                    and "apikey" not in lower_val
                    and "api_key" not in lower_val
                    and "pass" not in lower_val
                ):
                    return val

                val = _PATH_RE.sub(r"\1[REDACTED_PATH]", val)
                val = _KEY_RE.sub("[REDACTED_KEY]", val)
                val = _GENERIC_SECRET_RE.sub(r"\1\2\1\3\4[REDACTED_SECRET]\4", val)
                return val
            if isinstance(val, (int, float)):
                return val
            if isinstance(val, dict):
                sanitized = {}
                for k, v in val.items():
                    # If the key itself looks sensitive, redact the value unless it's numeric
                    if (
                        isinstance(k, str)
                        and any(
                            s in k.lower()
                            for s in [
                                "password",
                                "secret",
                                "token",
                                "apikey",
                                "api_key",
                            ]
                        )
                        and not isinstance(v, (int, float))
                    ):
                        sanitized[k] = "[REDACTED_VALUE]"
                    else:
                        sanitized[k] = _do_sanitize(v)
                return sanitized
            if isinstance(val, list):
                return [_do_sanitize(i) for i in val]
            if isinstance(val, tuple):
                return tuple(_do_sanitize(i) for i in val)
            return val

        return _do_sanitize(data)

    def _append_jsonl(self, obj: dict[str, Any]) -> None:
        self._ensure_parent()
        # Ensure all data written to disk is sanitized
        sanitized_obj = self._sanitize_data(obj)
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(sanitized_obj, ensure_ascii=False) + "\n")
        except PermissionError:
            import sys

            print(
                f"Telemetry warning: could not write to {self.log_file}",
                file=sys.stderr,
            )

    def _cost_avoided_usd(self, saved_tokens: int) -> float:
        if saved_tokens <= 0:
            return 0.0
        input_rate = float(self.rates.get("input_per_1m", 1.25) or 1.25)
        return (saved_tokens / 1_000_000.0) * input_rate

    def log_error(self, error: str, context: Optional[dict[str, Any]] = None) -> None:
        """
        Log an error or bad response to a daily debug report.
        Sanitizes personal information (device paths, usernames).
        """
        from datetime import datetime

        sanitized_error = self._sanitize_data(error)
        sanitized_context = self._sanitize_data(context or {})

        event = {
            "ts": time.time(),
            "type": "error",
            "message": sanitized_error,
            "context": sanitized_context,
        }

        date_str = datetime.now().strftime("%Y-%m-%d")
        debug_log_path = _DEBUG_LOG_DIR / f"braindrain_debug_report_{date_str}.md"
        debug_log_path.parent.mkdir(parents=True, exist_ok=True)

        header_exists = debug_log_path.exists()
        with open(debug_log_path, "a", encoding="utf-8") as f:
            if not header_exists:
                f.write(f"# BRAINDRAIN Debug Report — {date_str}\n\n")
            f.write(f"### [{datetime.now().strftime('%H:%M:%S')}] Error\n")
            f.write(f"- **Message**: {sanitized_error}\n")
            if sanitized_context:
                f.write(f"- **Context**: `{json.dumps(sanitized_context)}`\n")
            f.write("\n---\n\n")

        self._append_jsonl(event)

    def record_cache_hit(
        self,
        *,
        tool_name: str,
        payload_hash: str,
    ) -> bool:
        """Increment cache_hits when prefix-stable payload is unchanged (e.g. env context)."""
        prior = self._env_context_hash
        self._env_context_hash = payload_hash
        if prior is not None and prior == payload_hash:
            self.cache_hits += 1
            event = {
                "ts": time.time(),
                "type": "cache_hit",
                "tool": tool_name,
                "payload_hash": payload_hash,
            }
            self._append_jsonl(event)
            return True
        return False

    def record(
        self,
        *,
        tool_name: str,
        raw_text: str,
        actual_text: str,
        module: str = "output_sandbox",
        meta: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        raw_tokens = self.estimator.estimate(raw_text)
        actual_tokens = self.estimator.estimate(actual_text)

        agg = self.tools.setdefault(tool_name, ToolAggregate())
        agg.calls += 1
        agg.tokens_in_raw_est += raw_tokens
        agg.tokens_in_actual_est += actual_tokens

        saved = max(0, raw_tokens - actual_tokens)
        self.module_attribution[module] = self.module_attribution.get(module, 0) + saved
        self.cost_avoided_usd += self._cost_avoided_usd(saved)

        event = {
            "ts": time.time(),
            "tool": tool_name,
            "module": module,
            "tokens_in_raw_est": raw_tokens,
            "tokens_in_actual_est": actual_tokens,
            "tokens_saved_est": saved,
            "cost_avoided_usd_est": round(self._cost_avoided_usd(saved), 6),
            "meta": meta or {},
        }
        # Sanitize event before returning and before appending to JSONL
        sanitized_event = self._sanitize_data(event)
        self._append_jsonl(sanitized_event)
        return sanitized_event

    def snapshot(self) -> dict[str, Any]:
        totals_raw = sum(a.tokens_in_raw_est for a in self.tools.values())
        totals_actual = sum(a.tokens_in_actual_est for a in self.tools.values())
        totals_saved = max(0, totals_raw - totals_actual)
        pct = (totals_saved / totals_raw * 100.0) if totals_raw > 0 else 0.0
        return {
            "started_at": self.started_at,
            "uptime_seconds": int(time.time() - self.started_at),
            "tokens_in_raw_est": totals_raw,
            "tokens_in_actual_est": totals_actual,
            "tokens_saved_est": totals_saved,
            "saved_pct_est": round(pct, 2),
            "cache_hits": self.cache_hits,
            "cost_avoided_usd": round(self.cost_avoided_usd, 6),
            "module_attribution": self.module_attribution,
            "tools": {
                name: {
                    "calls": agg.calls,
                    "tokens_in_raw_est": agg.tokens_in_raw_est,
                    "tokens_in_actual_est": agg.tokens_in_actual_est,
                    "tokens_saved_est": agg.tokens_saved_est,
                    "saved_pct_est": round(agg.saved_pct_est, 2),
                }
                for name, agg in sorted(
                    self.tools.items(), key=lambda kv: -kv[1].tokens_saved_est
                )
            },
        }


def telemetry_from_config(cost_tracking: dict[str, Any]) -> TelemetrySession:
    log_path = cost_tracking.get("log_file") or "~/.braindrain/costs/session.jsonl"
    expanded = os.path.expanduser(str(log_path))
    rates = cost_tracking.get("rates") or {}
    if not isinstance(rates, dict):
        rates = {}
    return TelemetrySession(
        log_file=Path(expanded),
        estimator=build_estimator(cost_tracking),
        rates={
            "input_per_1m": float(rates.get("input_per_1m", 1.25) or 1.25),
            "output_per_1m": float(rates.get("output_per_1m", 6.0) or 6.0),
            "cache_read_per_1m": float(rates.get("cache_read_per_1m", 0.25) or 0.25),
        },
    )
