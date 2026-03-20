#!/usr/bin/env bash
# =============================================================================
# BRAINDRAIN — install.sh
# One-command setup: runtime checks, venv, full deps, env probe, guided MCP setup.
# =============================================================================

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'
info()  { echo -e "${CYAN}▸${RESET} $*"; }
ok()    { echo -e "${GREEN}✓${RESET} $*"; }
warn()  { echo -e "${YELLOW}⚠${RESET}  $*"; }
die()   { echo -e "${RED}✗${RESET}  $*" >&2; exit 1; }
header(){ echo -e "\n${BOLD}$*${RESET}"; }

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$REPO/.venv"
LOG_DIR="$REPO/.gstack/install-logs"
LOG_FILE="$LOG_DIR/install-$(date +%Y%m%d-%H%M%S).log"
mkdir -p "$LOG_DIR"
touch "$LOG_FILE"
cd "$REPO"

OS="$(uname -s)"
ARCH="$(uname -m)"
START_TS="$(date +%s)"

PIP_OK=0
HANDSHAKE_OK=0
MCP_CONFIG_STATUS="skipped"

header "=== BRAINDRAIN installer ==="
info "Repo: $REPO"
info "Log:  $LOG_FILE"

choose_python() {
    local preferred=("$@")
    local c
    for c in "${preferred[@]}"; do
        if command -v "$c" >/dev/null 2>&1; then
            echo "$c"
            return 0
        fi
    done
    return 1
}

python_version_tuple() {
    "$1" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"
}

python_is_supported() {
    local py="$1"
    local major minor
    major="$("$py" -c 'import sys; print(sys.version_info.major)' 2>/dev/null || echo 0)"
    minor="$("$py" -c 'import sys; print(sys.version_info.minor)' 2>/dev/null || echo 0)"
    if [[ "$major" -ne 3 ]]; then return 1; fi
    if [[ "$minor" -lt 11 ]]; then return 1; fi
    if [[ "$minor" -gt 13 ]]; then return 2; fi
    return 0
}

pip_with_retry() {
    local desc="$1"
    shift
    local attempt max_attempts
    max_attempts=3
    attempt=1
    while (( attempt <= max_attempts )); do
        info "$desc (attempt $attempt/$max_attempts)"
        if "$@" 2>&1 | tee -a "$LOG_FILE"; then
            return 0
        fi
        if (( attempt == max_attempts )); then
            return 1
        fi
        warn "Install step failed. Retrying in 3s..."
        sleep 3
        attempt=$((attempt + 1))
    done
}

header "1. Python interpreter"
PYTHON="${PYTHON:-}"

if [[ -z "$PYTHON" ]]; then
    PYTHON="$(choose_python python3.13 python3.12 python3.11 python3 || true)"
fi
[[ -z "$PYTHON" ]] && die "No Python found. Install Python 3.11-3.13 and retry."

if ! PYVER="$(python_version_tuple "$PYTHON" 2>/dev/null)"; then
    die "'$PYTHON' is not a working Python interpreter."
fi
PYTHON_REAL="$("$PYTHON" -c "import sys; print(sys.executable)")"

python_is_supported "$PYTHON" || {
    code=$?
    if [[ "$code" -eq 1 ]]; then
        die "Python 3.11-3.13 required. Found $PYTHON -> $PYVER. Try PYTHON=python3.12 ./install.sh"
    fi
    die "Python 3.14+ is not supported for first-run install yet (wheel availability). Found $PYTHON -> $PYVER. Install python3.12 or python3.13."
}

if echo "$PYTHON_REAL" | grep -q "pyenv/shims"; then
    warn "pyenv shim detected ($PYTHON_REAL)."
    warn "If install fails, retry with explicit interpreter (example: PYTHON=/usr/bin/python3.12 ./install.sh)."
fi
ok "Using $PYTHON -> $PYVER ($PYTHON_REAL)"

header "2. Environment file (early)"
if [[ -f "$REPO/.env.dev" ]]; then
    ok ".env.dev already exists"
else
    cp "$REPO/.env.example" "$REPO/.env.dev"
    ok "Created .env.dev from .env.example"
    warn "Edit .env.dev to set API keys/providers as needed."
fi

header "3. Virtual environment"
if [[ -d "$VENV" ]]; then
    VENV_VER="$("$VENV/bin/python" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "unknown")"
    ok "venv already exists ($VENV_VER)"
else
    info "Creating venv at $VENV ..."
    "$PYTHON" -m venv "$VENV" 2>&1 | tee -a "$LOG_FILE"
    ok "venv created"
fi
VENV_PYTHON="$VENV/bin/python"
VENV_PIP="$VENV/bin/pip"

header "4. Dependencies (full install)"
info "Upgrading pip/setuptools/wheel ..."
pip_with_retry "bootstrap pip tooling" "$VENV_PIP" install --upgrade pip setuptools wheel || die "pip bootstrap failed (see $LOG_FILE)."

if [[ "$OS" == "Linux" ]]; then
    if ! command -v nvidia-smi >/dev/null 2>&1; then
        export PIP_EXTRA_INDEX_URL="${PIP_EXTRA_INDEX_URL:-https://download.pytorch.org/whl/cpu}"
        export PIP_PREFER_BINARY=1
        info "Linux CPU-only mode detected; enabling PyTorch CPU wheel index."
        info "PIP_EXTRA_INDEX_URL=$PIP_EXTRA_INDEX_URL"
    else
        info "NVIDIA GPU detected; keeping default PyPI resolution."
    fi
fi

if pip_with_retry "install requirements.txt" "$VENV_PIP" install -r "$REPO/requirements.txt"; then
    PIP_OK=1
    ok "Dependencies installed"
else
    warn "Dependency install failed. Review: $LOG_FILE"
fi

header "5. AGENTS.md generation + env probe"
AGENTS_TEMPLATE="$REPO/AGENTS.md.template"
AGENTS_OUT="$REPO/AGENTS.md"
DETECTED_APPS_JSON='{}'
if [[ -f "$AGENTS_TEMPLATE" ]] && [[ "$PIP_OK" -eq 1 ]]; then
    PROBE_PAYLOAD="$("$VENV_PYTHON" - <<'PYEOF'
import json, re, sys
from pathlib import Path
from braindrain.env_probe import get_env_context

repo = Path(".")
result = get_env_context(refresh=True)
template = (repo / "AGENTS.md.template").read_text(encoding="utf-8")
block = result["agents_md_block"]
new_content = re.sub(
    r"<!-- ENV_CONTEXT_START -->.*?<!-- ENV_CONTEXT_END -->",
    f"<!-- ENV_CONTEXT_START -->\n{block}\n<!-- ENV_CONTEXT_END -->",
    template,
    flags=re.DOTALL,
)
(repo / "AGENTS.md").write_text(new_content, encoding="utf-8")
apps = result.get("summary", {}).get("app_configs", {})
print(json.dumps({"probe_timestamp": result["probe_timestamp"], "app_configs": apps}))
PYEOF
)"
    DETECTED_APPS_JSON="$("$VENV_PYTHON" - <<'PYEOF' "$PROBE_PAYLOAD"
import json, sys
payload = json.loads(sys.argv[1])
print(json.dumps(payload.get("app_configs", {})))
PYEOF
)"
    ok "AGENTS.md generated"
    info "Probe timestamp: $("$VENV_PYTHON" - <<'PYEOF' "$PROBE_PAYLOAD"
import json, sys
print(json.loads(sys.argv[1]).get("probe_timestamp", "unknown"))
PYEOF
)"
else
    warn "Skipping AGENTS.md generation (template missing or dependencies failed)."
fi

header "6. Launcher permissions"
chmod +x "$REPO/config/braindrain"
ok "config/braindrain is executable"

header "7. Guided MCP config install"
if [[ "$PIP_OK" -eq 1 ]] && [[ -t 0 ]]; then
    read -r -p "Configure MCP files now (interactive checklist)? [Y/n]: " MCP_SETUP_CHOICE
    MCP_SETUP_CHOICE="${MCP_SETUP_CHOICE:-Y}"
    if [[ "$MCP_SETUP_CHOICE" =~ ^[Yy]$ ]]; then
        if "$VENV_PYTHON" "$REPO/scripts/install/configure_mcp.py" \
            --launcher "$REPO/config/braindrain" \
            --detected-configs "$DETECTED_APPS_JSON"; then
            MCP_CONFIG_STATUS="updated_or_verified"
            ok "MCP config step complete"
        else
            MCP_CONFIG_STATUS="error"
            warn "MCP config step reported an error."
        fi
    else
        MCP_CONFIG_STATUS="user_skipped"
        warn "Skipped MCP config updates by user choice."
    fi
else
    warn "Skipping MCP config updates (non-interactive session or failed deps)."
fi

header "8. Self-test (MCP handshake)"
if [[ "${SKIP_TEST:-0}" == "1" ]]; then
    warn "SKIP_TEST=1 — skipping self-test"
else
    HANDSHAKE='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"install-test","version":"0"}}}'
    RESPONSE="$(echo "$HANDSHAKE" | "$REPO/config/braindrain" 2>>"$LOG_FILE" || true)"
    if echo "$RESPONSE" | grep -q '"serverInfo"'; then
        HANDSHAKE_OK=1
        SERVER_NAME="$(echo "$RESPONSE" | "$VENV_PYTHON" -c "import json,sys; print(json.load(sys.stdin)['result']['serverInfo']['name'])" 2>/dev/null || echo "braindrain")"
        ok "MCP handshake OK — server: $SERVER_NAME"
    else
        warn "MCP handshake failed. See log: $LOG_FILE"
        warn "Manual check: echo '$HANDSHAKE' | $REPO/config/braindrain 2>&1"
    fi
fi

ELAPSED="$(( $(date +%s) - START_TS ))"
header "=== Installation status ==="
echo "Platform:           $OS/$ARCH"
echo "Python:             $PYTHON ($PYVER)"
echo "Dependencies:       $([[ "$PIP_OK" -eq 1 ]] && echo "ok" || echo "failed")"
echo ".env.dev:           $([[ -f "$REPO/.env.dev" ]] && echo "present" || echo "missing")"
echo "MCP config updates: $MCP_CONFIG_STATUS"
echo "Handshake:          $([[ "$HANDSHAKE_OK" -eq 1 ]] && echo "ok" || echo "needs-attention")"
echo "Install log:        $LOG_FILE"
echo "Elapsed:            ${ELAPSED}s"

echo ""
echo -e "${BOLD}Next steps${RESET}"
echo "1) Restart/reload selected IDEs/agents after MCP config changes."
echo "2) In your current AI workspace, run:"
echo "   - get_env_context()"
echo "   - search_tools(\"environment + mcp setup\", top_k=5)"
echo "   - get_token_dashboard()"
echo ""
echo -e "${BOLD}Update command${RESET}"
echo "cd \"$REPO\" && \"$VENV_PIP\" install -r requirements.txt"
