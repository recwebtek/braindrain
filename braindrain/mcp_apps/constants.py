"""MCP Apps (`ui://`) resource URIs for braindrain inline dashboards."""

TOKEN_DASHBOARD_URI = "ui://braindrain/token-dashboard.html"
PLAN_BOARD_URI = "ui://braindrain/plan-board.html"

# App-only refresh tools (hidden from model catalog; iframe may call via host proxy).
POLL_TOKEN_DASHBOARD_TOOL = "poll_token_dashboard"
POLL_PLAN_BOARD_TOOL = "poll_plan_board"
