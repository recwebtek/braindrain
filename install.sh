#!/usr/bin/env bash
# =============================================================================
# BRAINDRAIN — install.sh
# New-device setup: venv, dependencies, AGENTS.md generation, self-test.
#
# Usage:
#   chmod +x install.sh && ./install.sh
#
# Options:
#   PYTHON=python3.12 ./install.sh   # specify Python interpreter
#   SKIP_TEST=1 ./install.sh         # skip the MCP handshake self-test
# =============================================================================

set -euo pipefail

# ── Colours ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

info()  { echo -e "${CYAN}▸${RESET} $*"; }
ok()    { echo -e "${GREEN}✓${RESET} $*"; }
warn()  { echo -e "${YELLOW}⚠${RESET}  $*"; }
die()   { echo -e "${RED}✗${RESET}  $*" >&2; exit 1; }
header(){ echo -e "\n${BOLD}$*${RESET}"; }

# ── Repo root (works regardless of cwd) ──────────────────────────────────────
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$REPO/.venv"

header "=== BRAINDRAIN installer ==="
info "Repo: $REPO"

# ── 1. Find a suitable Python ────────────────────────────────────────────────
header "1. Python interpreter"

PYTHON="${PYTHON:-}"

# If caller didn't specify, try common names in order
if [[ -z "$PYTHON" ]]; then
    for candidate in python3.12 python3.11 python3.13 python3; do
        if command -v "$candidate" &>/dev/null; then
            PYTHON="$candidate"
            break
        fi
    done
fi

[[ -z "$PYTHON" ]] && die "No Python 3.11+ found. Install it first (brew install python@3.12)."

# Verify version >= 3.11
PYVER=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "")
[[ -z "$PYVER" ]] && die "'$PYTHON' is not a working Python interpreter."

PYMAJOR=$(echo "$PYVER" | cut -d. -f1)
PYMINOR=$(echo "$PYVER" | cut -d. -f2)

if [[ "$PYMAJOR" -lt 3 ]] || [[ "$PYMAJOR" -eq 3 && "$PYMINOR" -lt 11 ]]; then
    die "Python 3.11+ required. Found $PYTHON → $PYVER. Set PYTHON=python3.12 and retry."
fi

# Warn if pyenv shim is active — it often resolves to an old version
PYTHON_REAL=$("$PYTHON" -c "import sys; print(sys.executable)")
if echo "$PYTHON_REAL" | grep -q "pyenv/shims"; then
    warn "pyenv shim detected ($PYTHON → $PYVER via shims)."
    warn "Consider using PYTHON=/usr/local/bin/python3.12 or similar to avoid shim issues."
fi

ok "Using $PYTHON → $PYVER ($PYTHON_REAL)"

# ── 2. Create virtualenv ─────────────────────────────────────────────────────
header "2. Virtual environment"

if [[ -d "$VENV" ]]; then
    VENV_VER=$("$VENV/bin/python" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "unknown")
    ok "venv already exists ($VENV_VER) — skipping creation"
else
    info "Creating venv at $VENV ..."
    "$PYTHON" -m venv "$VENV"
    ok "venv created"
fi

VENV_PYTHON="$VENV/bin/python"
VENV_PIP="$VENV/bin/pip"

# ── 3. Install / upgrade dependencies ───────────────────────────────────────
header "3. Dependencies"

info "Upgrading pip..."
"$VENV_PIP" install -q --upgrade pip

info "Installing from requirements.txt..."
"$VENV_PIP" install -q -r "$REPO/requirements.txt"
ok "Dependencies installed"

# ── 4. Create .env.dev if missing ───────────────────────────────────────────
header "4. Environment file"

if [[ -f "$REPO/.env.dev" ]]; then
    ok ".env.dev already exists — skipping"
else
    cp "$REPO/.env.example" "$REPO/.env.dev"
    ok "Created .env.dev from .env.example"
    warn "Edit .env.dev to set your API keys (GitHub, LM Studio, etc.)"
fi

# ── 5. Generate AGENTS.md ────────────────────────────────────────────────────
header "5. AGENTS.md generation"

AGENTS_TEMPLATE="$REPO/AGENTS.md.template"
AGENTS_OUT="$REPO/AGENTS.md"

if [[ ! -f "$AGENTS_TEMPLATE" ]]; then
    warn "AGENTS.md.template not found — skipping AGENTS.md generation"
elif [[ -f "$AGENTS_OUT" ]]; then
    ok "AGENTS.md already exists — skipping (run 'refresh_env_context()' in any session to update)"
else
    info "Running OS environment probe (~5s)..."
    "$VENV_PYTHON" - <<'PYEOF'
import sys, re
from pathlib import Path

repo = Path(__file__).parent if False else Path(".")
sys.path.insert(0, str(repo))

from braindrain.env_probe import get_env_context

result = get_env_context(refresh=True)
template = (repo / "AGENTS.md.template").read_text()
block = result["agents_md_block"]

new_content = re.sub(
    r"<!-- ENV_CONTEXT_START -->.*?<!-- ENV_CONTEXT_END -->",
    f"<!-- ENV_CONTEXT_START -->\n{block}\n<!-- ENV_CONTEXT_END -->",
    template,
    flags=re.DOTALL,
)
(repo / "AGENTS.md").write_text(new_content)
print(f"  probe_timestamp: {result['probe_timestamp']}")
print(f"  cache: ~/.braindrain/env_context.json")
PYEOF
    ok "AGENTS.md generated"
fi

# ── 6. Make launcher executable ─────────────────────────────────────────────
header "6. Launcher permissions"

chmod +x "$REPO/config/braindrain"
ok "config/braindrain is executable"

# ── 7. Self-test (MCP handshake) ─────────────────────────────────────────────
header "7. Self-test"

if [[ "${SKIP_TEST:-0}" == "1" ]]; then
    warn "SKIP_TEST=1 — skipping self-test"
else
    info "Sending MCP initialize to config/braindrain..."
    HANDSHAKE='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"install-test","version":"0"}}}'

    RESPONSE=$(echo "$HANDSHAKE" | "$REPO/config/braindrain" 2>/dev/null || echo "")

    if echo "$RESPONSE" | grep -q '"serverInfo"'; then
        SERVER_NAME=$(echo "$RESPONSE" | "$VENV_PYTHON" -c \
            "import json,sys; d=json.load(sys.stdin); print(d['result']['serverInfo']['name'])" 2>/dev/null || echo "braindrain")
        ok "MCP handshake OK — server: $SERVER_NAME"
    else
        warn "MCP handshake failed or produced no output."
        warn "Try manually: echo '$HANDSHAKE' | $REPO/config/braindrain 2>&1"
    fi
fi

# ── Done ──────────────────────────────────────────────────────────────────────
header "=== Installation complete ==="
echo ""
echo -e "${BOLD}Add to your IDE's MCP config:${RESET}"
echo ""
echo -e "  ${CYAN}Cursor / Windsurf / Codex / Antigravity (mcpServers):${RESET}"
echo    "  \"command\": \"$REPO/config/braindrain\""
echo ""
echo -e "  ${CYAN}Zed (context_servers):${RESET}"
echo    "  \"command\": \"$REPO/config/braindrain\""
echo ""
echo -e "  ${CYAN}OpenCode (mcp → type local):${RESET}"
echo    "  \"command\": [\"$REPO/config/braindrain\"]"
echo ""
echo -e "${BOLD}To update later:${RESET}"
echo    "  cd $REPO && git pull && $VENV_PIP install -r requirements.txt"
echo ""
echo -e "${BOLD}To refresh env context in any agent session:${RESET}"
echo    "  call: refresh_env_context()"
echo ""
