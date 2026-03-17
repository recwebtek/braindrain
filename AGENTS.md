# AGENTS.md - AI Agent Rules & Best Practices

This file contains instructions for AI agents working in this repository. Place in project root.

---

## BRAINDRAIN MCP Tools

Always use braindrain MCP tools for code discovery and context management.

### Required Behavior

**Before any code search/retrieval task:**
1. Run `braindrain_search_tools` to discover available MCP tools
2. Use discovered tools (repo_mapper, jcodemunch) instead of native grep/read
3. NEVER assume a tool doesn't exist - search first

**For multi-step tasks:**
1. Check `braindrain_list_workflows` for pre-built solutions
2. Use existing workflows before creating custom implementations

**For cost/performance awareness:**
- Periodically check `braindrain_get_token_stats`
- Use search to find previous results before re-executing operations

### Tool Priority Order

1. `braindrain_search_tools` - Discover available tools
2. Discovered MCP tool - Execute via found tool
3. Native fallback - grep, read, glob only if MCP unavailable

### Context Compression

All tool outputs route through context-mode FTS5 index. Use search to find:
- Previous search results
- Indexed code chunks  
- Past tool outputs

---

## MCP Tool Definitions

### Hot Tools (Always Available)
- `braindrain_search_tools` - Search and discover MCP tools
- `braindrain_list_workflows` - List available workflows
- `braindrain_get_token_stats` - Show session token statistics
- `context_mode` - FTS5 output sandbox with search index

### Deferred Tools (Load on Demand)
- `repo_mapper` - PageRank dependency graph, token-budgeted repo map
- `jcodemunch` - Symbol-level code retrieval
- `github` - GitHub operations (PR, issues, commits)

---

## Usage Examples

```bash
# Find tools for codebase analysis
braindrain_search_tools(query="codebase symbols graph")

# List available workflows  
braindrain_list_workflows

# Check token savings this session
braindrain_get_token_stats
```

---

## Supported Platforms

This AGENTS.md works with:
- **Cursor** - Uses `.cursorrules` in project root
- **Codex** - Uses `.codexrules` in project root
- **OpenCode** - Uses AGENTS.md in project root
- **Windsurf** - Uses `.windsurfrules` in project root
- **Other Claude-based agents** - Read AGENTS.md automatically