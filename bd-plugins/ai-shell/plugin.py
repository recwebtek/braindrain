"""AI Shell plugin runtime for Braindrain."""

from __future__ import annotations

import hashlib
import json
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any

import yaml

from braindrain.session import SessionStore

plugin_api_version = "1.0"

DEFAULT_BLOCKED_REASONS = {
    "outside_project_root",
    "interactive_tty",
    "destructive_command",
    "network_blocked",
    "not_allowlisted",
    "invalid_args",
}


def discover() -> dict[str, Any]:
    return {
        "name": "ai_shell",
        "plugin_api_version": plugin_api_version,
        "tools": ["ai_shell_run", "ai_shell_state_sync"],
    }


def load(context: dict[str, Any]) -> "AIShellPluginRuntime":
    return AIShellPluginRuntime(context)


class AIShellPluginRuntime:
    def __init__(self, context: dict[str, Any]) -> None:
        self.repo_root = Path(context["repo_root"]).resolve()
        self.default_mode = str(context.get("default_mode", "hybrid") or "hybrid")
        self.policy_path = Path(context["policy_path"]).expanduser()
        self.session_store = SessionStore(context["session_db_path"])
        self.policy = self._load_policy()
        self._safe_git_subcommands = {
            "status",
            "diff",
            "log",
            "show",
            "branch",
            "rev-parse",
            "remote",
            "ls-files",
        }

    def register_tools(self, registry) -> None:
        registry.register("ai_shell_run", self.ai_shell_run, "Run AI shell command")
        registry.register(
            "ai_shell_state_sync",
            self.ai_shell_state_sync,
            "Get canonical AI shell state",
        )

    def healthcheck(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "plugin": "ai_shell",
            "policy_path": str(self.policy_path),
            "policy_loaded": bool(self.policy),
        }

    def shutdown(self) -> None:
        return None

    def ai_shell_state_sync(self, session_id: str, project_id: str = "default") -> dict[str, Any]:
        state = self._ensure_state(session_id=session_id, project_id=project_id, cwd_hint=None)
        return {
            "session_id": state["session_id"],
            "project_id": state["project_id"],
            "cwd_after": state["cwd"],
            "mode_default": self.default_mode,
            "status": "ok",
        }

    def ai_shell_run(
        self,
        session_id: str,
        command: str,
        cwd: str | None = None,
        requested_mode: str | None = None,
        project_id: str = "default",
    ) -> dict[str, Any]:
        state = self._ensure_state(session_id=session_id, project_id=project_id, cwd_hint=cwd)
        requested = (requested_mode or "").strip() or self.default_mode
        mode = requested if requested in {"simulated", "hybrid", "real_world"} else self.default_mode

        policy_eval = self._evaluate_policy(command=command, cwd=state["cwd"], requested_mode=mode)
        mode_used = self._resolve_mode(mode=mode, policy_decision=policy_eval["policy_decision"])

        if policy_eval["policy_decision"] == "block":
            result = {
                "output_text": f"blocked: {policy_eval['blocked_reason']}",
                "signals": {},
                "cwd_after": state["cwd"],
                "mode_used": mode_used,
                "safety": policy_eval,
                "session_id": session_id,
            }
            self._record_command(
                session_id=session_id,
                project_id=project_id,
                command=command,
                mode_used=mode_used,
                policy_decision=policy_eval["policy_decision"],
                output_text=result["output_text"],
                exit_code=1,
            )
            return result

        if command.strip().startswith("cd"):
            return self._handle_cd(
                session_id=session_id,
                project_id=project_id,
                command=command,
                mode_used=mode_used,
                policy_eval=policy_eval,
                cwd_before=state["cwd"],
            )

        if mode_used == "simulated":
            output = f"[simulated] {command.strip()}"
            exit_code = 0
        else:
            output, exit_code = self._run_guarded(command=command, cwd=state["cwd"])

        self._record_command(
            session_id=session_id,
            project_id=project_id,
            command=command,
            mode_used=mode_used,
            policy_decision=policy_eval["policy_decision"],
            output_text=output,
            exit_code=exit_code,
        )
        self.session_store.prune_ai_shell_history(session_id=session_id, project_id=project_id)
        return {
            "output_text": output,
            "signals": {},
            "cwd_after": state["cwd"],
            "mode_used": mode_used,
            "safety": policy_eval,
            "session_id": session_id,
        }

    def _handle_cd(
        self,
        *,
        session_id: str,
        project_id: str,
        command: str,
        mode_used: str,
        policy_eval: dict[str, Any],
        cwd_before: str,
    ) -> dict[str, Any]:
        tokens = shlex.split(command)
        target = tokens[1] if len(tokens) > 1 else str(Path.home())
        next_path = (Path(cwd_before) / target).expanduser().resolve()
        if not str(next_path).startswith(str(self.repo_root)):
            policy_eval = dict(policy_eval)
            policy_eval["policy_decision"] = "block"
            policy_eval["blocked_reason"] = "outside_project_root"
            output = "blocked: outside_project_root"
            self._record_command(
                session_id=session_id,
                project_id=project_id,
                command=command,
                mode_used=mode_used,
                policy_decision=policy_eval["policy_decision"],
                output_text=output,
                exit_code=1,
            )
            return {
                "output_text": output,
                "signals": {},
                "cwd_after": cwd_before,
                "mode_used": mode_used,
                "safety": policy_eval,
                "session_id": session_id,
            }

        self.session_store.upsert_ai_shell_session(
            session_id=session_id,
            project_id=project_id,
            cwd=str(next_path),
            env_delta_json={},
        )
        self.session_store.append_ai_shell_event(
            session_id=session_id,
            project_id=project_id,
            event_type="cd_success",
            payload={"cwd_after": str(next_path)},
        )
        self._record_command(
            session_id=session_id,
            project_id=project_id,
            command=command,
            mode_used=mode_used,
            policy_decision=policy_eval["policy_decision"],
            output_text=f"__CD__:{next_path}",
            exit_code=0,
        )
        self.session_store.prune_ai_shell_history(session_id=session_id, project_id=project_id)
        return {
            "output_text": f"__CD__:{next_path}",
            "signals": {"cd": str(next_path)},
            "cwd_after": str(next_path),
            "mode_used": mode_used,
            "safety": policy_eval,
            "session_id": session_id,
        }

    def _run_guarded(self, *, command: str, cwd: str) -> tuple[str, int]:
        proc = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=8,
        )
        out = (proc.stdout or proc.stderr or "").strip()
        return (out or "(no output)"), int(proc.returncode)

    def _ensure_state(self, *, session_id: str, project_id: str, cwd_hint: str | None) -> dict[str, str]:
        existing = self.session_store.get_ai_shell_session(session_id=session_id, project_id=project_id)
        if existing:
            return {
                "session_id": existing.session_id,
                "project_id": existing.project_id,
                "cwd": existing.cwd,
            }
        initial_cwd = self._normalize_cwd(cwd_hint or str(self.repo_root))
        state = self.session_store.upsert_ai_shell_session(
            session_id=session_id,
            project_id=project_id,
            cwd=initial_cwd,
            env_delta_json={},
        )
        return {"session_id": state.session_id, "project_id": state.project_id, "cwd": state.cwd}

    def _normalize_cwd(self, raw: str) -> str:
        resolved = Path(raw).expanduser().resolve()
        if not str(resolved).startswith(str(self.repo_root)):
            return str(self.repo_root)
        return str(resolved)

    def _load_policy(self) -> dict[str, Any]:
        if not self.policy_path.exists():
            return {}
        with self.policy_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data

    def _evaluate_policy(self, *, command: str, cwd: str, requested_mode: str) -> dict[str, Any]:
        parsed = shlex.split(command) if command.strip() else []
        if not parsed:
            return self._policy_block("invalid_args", "rule:empty_command", cwd, requested_mode)

        cmd = parsed[0]
        args = parsed[1:]
        trace = [
            "normalize_input",
            "validate_parseable",
            "enforce_project_boundary",
            "evaluate_deny_rules",
            "evaluate_allow_rules",
            "resolve_mode_gate",
        ]
        if not str(Path(cwd).resolve()).startswith(str(self.repo_root)):
            return self._policy_block("outside_project_root", "rule:project_root", cwd, requested_mode)

        blocked = self._as_normalized_string_set(self.policy.get("blocked_commands", []))
        blocked_prefixes = self._as_normalized_string_set(self.policy.get("blocked_prefixes", []))
        allowlist = self._as_normalized_string_set(self.policy.get("allow_commands", []))

        if cmd in blocked or any(command.strip().startswith(prefix) for prefix in blocked_prefixes if prefix):
            reason = "destructive_command"
            if "curl" in cmd or "wget" in cmd:
                reason = "network_blocked"
            return self._policy_block(reason, f"deny:{cmd}", cwd, requested_mode)

        tier = self._command_tier(cmd, allowlist)
        if tier == "simulated-only":
            return {
                "policy_decision": "force_simulated",
                "policy_rule_id": f"tier:simulated_only:{cmd}",
                "blocked_reason": None,
                "decision_trace": trace,
            }

        if tier is None:
            if requested_mode == "simulated":
                return {
                    "policy_decision": "force_simulated",
                    "policy_rule_id": "allow:simulated_unknown",
                    "blocked_reason": None,
                    "decision_trace": trace,
                }
            return self._policy_block("not_allowlisted", f"deny:{cmd}", cwd, requested_mode)

        if any(arg in {"-i", "--interactive"} for arg in args):
            return self._policy_block("interactive_tty", "deny:interactive", cwd, requested_mode)

        if cmd == "git" and args:
            subcommand = args[0]
            if subcommand not in self._safe_git_subcommands:
                if requested_mode == "simulated":
                    return {
                        "policy_decision": "force_simulated",
                        "policy_rule_id": f"allow:git_simulated:{subcommand}",
                        "blocked_reason": None,
                        "decision_trace": trace,
                    }
                return self._policy_block("not_allowlisted", f"deny:git:{subcommand}", cwd, requested_mode)

        return {
            "policy_decision": "allow_real_world" if requested_mode == "real_world" else "force_simulated"
            if requested_mode == "simulated"
            else "allow_real_world",
            "policy_rule_id": f"allow:{cmd}",
            "blocked_reason": None,
            "decision_trace": trace,
        }

    def _policy_block(
        self, reason: str, rule_id: str, cwd: str, requested_mode: str
    ) -> dict[str, Any]:
        blocked_reason = reason if reason in DEFAULT_BLOCKED_REASONS else "invalid_args"
        return {
            "policy_decision": "block",
            "policy_rule_id": rule_id,
            "blocked_reason": blocked_reason,
            "decision_trace": [
                "normalize_input",
                "validate_parseable",
                "enforce_project_boundary",
                "evaluate_deny_rules",
                f"blocked:{blocked_reason}",
                f"mode:{requested_mode}",
                f"cwd:{cwd}",
            ],
        }

    def _resolve_mode(self, *, mode: str, policy_decision: str) -> str:
        if policy_decision == "force_simulated":
            return "simulated"
        if policy_decision == "allow_real_world":
            return "real_world" if mode in {"real_world", "hybrid"} else "simulated"
        return "simulated"

    def _as_normalized_string_set(self, raw_values: Any) -> set[str]:
        normalized: set[str] = set()
        if isinstance(raw_values, list):
            for value in raw_values:
                if isinstance(value, str):
                    text = value.strip()
                    if text:
                        normalized.add(text)
        return normalized

    def _command_tier(self, command_name: str, allowlist: set[str]) -> str | None:
        tier1 = self._as_normalized_string_set(self.policy.get("tier_always_allow", []))
        tier2 = self._as_normalized_string_set(self.policy.get("tier_allow_with_constraints", []))
        tier3 = self._as_normalized_string_set(self.policy.get("tier_simulated_only", []))

        if command_name in tier3:
            return "simulated-only"
        if command_name in tier1:
            return "always-allow"
        if command_name in tier2:
            return "allow-with-constraints"
        if command_name in allowlist:
            return "always-allow"
        return None

    def _record_command(
        self,
        *,
        session_id: str,
        project_id: str,
        command: str,
        mode_used: str,
        policy_decision: str,
        output_text: str,
        exit_code: int,
    ) -> None:
        digest = hashlib.sha256(output_text.encode("utf-8")).hexdigest()[:16]
        request_bytes = len(command.encode("utf-8"))
        response_bytes = len(output_text.encode("utf-8"))
        estimated_tokens = int((request_bytes + response_bytes) / 4)
        self.session_store.append_ai_shell_command(
            session_id=session_id,
            project_id=project_id,
            command_text=command,
            mode_used=mode_used,
            policy_decision=policy_decision,
            exit_code=exit_code,
            output_digest=digest,
            request_bytes=request_bytes,
            response_bytes=response_bytes,
            estimated_tokens=estimated_tokens,
            created_at=time.time(),
        )
