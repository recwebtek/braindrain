"""MCP Apps (`ui://`) resource URIs for braindrain inline dashboards."""

TOKEN_DASHBOARD_URI = "ui://braindrain/token-dashboard.html"
PLAN_BOARD_URI = "ui://braindrain/plan-board.html"
SIGINT_MAP_URI = "ui://braindrain/sigint-map.html"

# App-only refresh tools (hidden from model catalog; iframe may call via host proxy).
POLL_TOKEN_DASHBOARD_TOOL = "poll_token_dashboard"
POLL_PLAN_BOARD_TOOL = "poll_plan_board"
POLL_SIGINT_MAP_TOOL = "poll_sigint_map"

# App-only plan board action tools (iframe tools/call).
AUDIT_PLAN_IMPLEMENTATION_TOOL = "audit_plan_implementation"
APPLY_PLAN_TODO_SYNC_TOOL = "apply_plan_todo_sync"
MARK_PLAN_MERGE_READY_TOOL = "mark_plan_merge_ready"
ARCHIVE_PLAN_TOOL = "archive_plan"
ENQUEUE_PLAN_CONTINUE_TOOL = "enqueue_plan_continue"
PLAN_BOARD_HANDOFF_TOOL = "plan_board_handoff"
