"""Token/cost telemetry for BRAINDRAIN.

MVP focus:
- Track estimated Claude/Anthropic token impact of routing large outputs through context-mode.
- Persist per-event JSONL to the configured log path.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


def estimate_claude_tokens(text: str) -> int:
    # Simple, fast approximation (~4 chars/token English-ish). Good enough to
    # prove directionality; can be replaced with provider-native counts later.
    if not text:
        return 0
    return max(1, len(text) // 4)


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
            # Fallback to current working directory if home dir is restricted
            fallback = Path(".logs") / self.log_file.name
            if self.log_file != fallback:
                self.log_file = fallback
                self.log_file.parent.mkdir(parents=True, exist_ok=True)

    def _append_jsonl(self, obj: dict[str, Any]) -> None:
        self._ensure_parent()
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(obj, ensure_ascii=False) + "\n")
        except PermissionError:
            # Last resort: just ignore or print to stderr if even fallback fails
            import sys
            print(f"Telemetry warning: could not write to {self.log_file}", file=sys.stderr)

    def log_error(self, error: str, context: Optional[dict[str, Any]] = None) -> None:
        """
        Log an error or bad response to a daily debug report.
        Sanitizes personal information (device paths, usernames).
        """
        import re
        from datetime import datetime

        # 1. Sanitize error string
        # Mask absolute paths starting with /Users/ or /Volumes/
        sanitized = re.sub(r"(/Users/[^/\s]+|/Volumes/[^/\s]+)", "[REDACTED_PATH]", error)
        
        # 2. Prepare event
        event = {
            "ts": time.time(),
            "type": "error",
            "message": sanitized,
            "context": context or {},
        }

        # 3. Write to daily debug report in .logs/
        # Use project root for .logs/ (assumed to be current working directory or relative to it)
        date_str = datetime.now().strftime("%Y-%m-%d")
        debug_log_path = Path(".logs") / f"braindrain_debug_report_{date_str}.md"
        
        # Ensure .logs exists
        debug_log_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Append to markdown report
        header_exists = debug_log_path.exists()
        with open(debug_log_path, "a", encoding="utf-8") as f:
            if not header_exists:
                f.write(f"# BRAINDRAIN Debug Report — {date_str}\n\n")
            
            f.write(f"### [{datetime.now().strftime('%H:%M:%S')}] Error\n")
            f.write(f"- **Message**: {sanitized}\n")
            if context:
                f.write(f"- **Context**: `{json.dumps(context)}`\n")
            f.write("\n---\n\n")

        # Also append to session JSONL
        self._append_jsonl(event)

    def record(
        self,
        *,
        tool_name: str,
        raw_text: str,
        actual_text: str,
        module: str = "output_sandbox",
        meta: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        raw_tokens = estimate_claude_tokens(raw_text)
        actual_tokens = estimate_claude_tokens(actual_text)

        agg = self.tools.setdefault(tool_name, ToolAggregate())
        agg.calls += 1
        agg.tokens_in_raw_est += raw_tokens
        agg.tokens_in_actual_est += actual_tokens

        saved = max(0, raw_tokens - actual_tokens)
        self.module_attribution[module] = self.module_attribution.get(module, 0) + saved

        event = {
            "ts": time.time(),
            "tool": tool_name,
            "module": module,
            "tokens_in_raw_est": raw_tokens,
            "tokens_in_actual_est": actual_tokens,
            "tokens_saved_est": saved,
            "meta": meta or {},
        }
        self._append_jsonl(event)
        return event

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
            "module_attribution": self.module_attribution,
            "tools": {
                name: {
                    "calls": agg.calls,
                    "tokens_in_raw_est": agg.tokens_in_raw_est,
                    "tokens_in_actual_est": agg.tokens_in_actual_est,
                    "tokens_saved_est": agg.tokens_saved_est,
                    "saved_pct_est": round(agg.saved_pct_est, 2),
                }
                for name, agg in sorted(self.tools.items(), key=lambda kv: -kv[1].tokens_saved_est)
            },
        }


def telemetry_from_config(cost_tracking: dict[str, Any]) -> TelemetrySession:
    log_path = cost_tracking.get("log_file") or "~/.braindrain/costs/session.jsonl"
    expanded = os.path.expanduser(str(log_path))
    return TelemetrySession(log_file=Path(expanded))

