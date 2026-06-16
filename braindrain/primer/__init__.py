"""Workspace primer split modules with compatibility re-exports."""

from .apply import run_ruler_apply
from .compat import compact_prime_result_for_mcp, sync_cursor_rules_from_ruler
from .deploy import (
    deploy_cursor_commands,
    deploy_cursor_hook_templates,
    deploy_cursor_skill_templates,
    deploy_operational_scripts,
    deploy_subagent_templates,
    deploy_templates,
)
from .detect import detect_prime_agents
from .memory import initialize_project_memory
from .prime import prime

__all__ = [
    "compact_prime_result_for_mcp",
    "deploy_cursor_commands",
    "deploy_cursor_hook_templates",
    "deploy_cursor_skill_templates",
    "deploy_operational_scripts",
    "deploy_subagent_templates",
    "deploy_templates",
    "detect_prime_agents",
    "initialize_project_memory",
    "prime",
    "run_ruler_apply",
    "sync_cursor_rules_from_ruler",
]

