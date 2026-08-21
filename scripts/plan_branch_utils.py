"""Shared plan → git branch naming, frontmatter parsing, and git helpers."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

# Frontmatter parser regexes (no PyYAML dependency — keeps scripts standalone).
FRONTMATTER_BLOCK_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|$)", re.DOTALL)
FRONTMATTER_KV_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*)\s*:\s*(.*?)\s*$")

CHILDREN_SPEC_ITEM_KEYS = ("id", "file", "name", "branch", "section", "branches")

BASE_BRANCH_FRONTMATTER_KEYS = ("base_branch", "baseBranch", "base")
BASE_BRANCH_CANDIDATES = ("main", "master", "develop", "trunk")

# How far above the code repo to look for a plan path (plans-at-workspace-root layouts).
PLAN_LOOKUP_ANCESTOR_DEPTH = 3


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def parse_frontmatter_body(body: str) -> dict[str, object]:
    """Parse one YAML frontmatter body (between ``---`` fences)."""
    out: dict[str, object] = {}
    current_list: list[str] | None = None

    for raw in body.splitlines():
        if not raw.strip():
            continue
        if current_list is not None and re.match(r"^\s+-\s+", raw):
            value = re.sub(r"^\s+-\s+", "", raw).strip()
            current_list.append(_strip_quotes(value))
            continue
        kv = FRONTMATTER_KV_RE.match(raw)
        if not kv:
            current_list = None
            continue
        key = kv.group(1)
        value = kv.group(2)
        current_list = None
        if not value:
            current_list = []
            out[key] = current_list
            continue
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            parts = [_strip_quotes(p.strip()) for p in inner.split(",") if p.strip()]
            out[key] = parts
            continue
        out[key] = _strip_quotes(value)
    return out


def parse_plan_frontmatter(path_or_text) -> dict[str, object]:
    """Parse leading YAML frontmatter (merges consecutive ``---`` blocks)."""
    if isinstance(path_or_text, Path):
        text = path_or_text.read_text(encoding="utf-8", errors="ignore")
    else:
        text = str(path_or_text or "")

    merged: dict[str, object] = {}
    pos = 0
    while pos < len(text):
        slice_text = text[pos:]
        match = FRONTMATTER_BLOCK_RE.match(slice_text)
        if not match:
            break
        merged.update(parse_frontmatter_body(match.group(1)))
        pos += match.end()
        remainder = text[pos:].lstrip("\n")
        if remainder.startswith("---"):
            pos = len(text) - len(remainder)
            continue
        break
    return merged


def _inject_frontmatter_key(text: str, key: str, value: str) -> str:
    match = FRONTMATTER_BLOCK_RE.match(text)
    if match:
        fm_block = match.group(0)
        fm_body = match.group(1)
        if re.search(rf"(?m)^{re.escape(key)}\s*:", fm_body):
            return text
        updated_body = fm_body.rstrip() + f"\n{key}: {value}\n"
        new_block = f"---\n{updated_body}---\n"
        return new_block + text[len(fm_block) :]
    return f"---\n{key}: {value}\n---\n\n{text}"


def set_frontmatter_key(text: str, key: str, value: str) -> str:
    """Insert or replace a frontmatter scalar key."""
    match = FRONTMATTER_BLOCK_RE.match(text)
    if not match:
        return _inject_frontmatter_key(text, key, value)
    fm_block = match.group(0)
    fm_body = match.group(1)
    key_re = re.compile(rf"(?m)^{re.escape(key)}\s*:\s*.*$")
    if key_re.search(fm_body):
        updated_body = key_re.sub(f"{key}: {value}", fm_body, count=1)
    else:
        updated_body = fm_body.rstrip() + f"\n{key}: {value}\n"
    new_block = f"---\n{updated_body}---\n"
    return new_block + text[len(fm_block) :]


def remove_frontmatter_scalar(fm_body: str, key: str) -> str:
    return re.sub(rf"(?m)^{re.escape(key)}\s*:\s*.*\n?", "", fm_body)


def remove_frontmatter_block(fm_body: str, key: str) -> str:
    lines = fm_body.splitlines()
    kept: list[str] = []
    skipping = False
    for line in lines:
        if re.match(rf"^{re.escape(key)}\s*:\s*$", line.strip()):
            skipping = True
            continue
        if skipping:
            if line and not line.startswith((" ", "-")) and FRONTMATTER_KV_RE.match(line):
                skipping = False
            else:
                continue
        kept.append(line)
    return "\n".join(kept).strip("\n")


def set_frontmatter_yaml_block(text: str, key: str, block_lines: list[str]) -> str:
    match = FRONTMATTER_BLOCK_RE.match(text)
    if not match:
        body = "\n".join(block_lines) + "\n"
        return f"---\n{body}---\n\n{text}"
    fm_body = match.group(1)
    fm_body = remove_frontmatter_block(fm_body, key)
    fm_body = fm_body.rstrip()
    block_text = "\n".join(block_lines).rstrip() + "\n"
    if fm_body:
        fm_body += "\n" + block_text
    else:
        fm_body = block_text
    new_block = f"---\n{fm_body}---\n"
    return new_block + text[len(match.group(0)) :]


def plan_body_after_frontmatter(text: str) -> str:
    match = FRONTMATTER_BLOCK_RE.match(text)
    if match:
        return text[match.end() :]
    return text


def parse_frontmatter_children_spec(text: str) -> list[dict[str, str]]:
    """Parse ``children_spec:`` list entries from plan frontmatter."""
    fm_lines: list[str] = []
    pos = 0
    while pos < len(text):
        match = FRONTMATTER_BLOCK_RE.match(text[pos:])
        if not match:
            break
        fm_lines.extend(match.group(1).splitlines())
        pos += match.end()
        remainder = text[pos:].lstrip("\n")
        if remainder.startswith("---"):
            pos = len(text) - len(remainder)
            continue
        break
    if not fm_lines:
        return []
    entries: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    in_block = False
    for raw in fm_lines:
        stripped = raw.strip()
        if not stripped:
            continue
        if re.match(r"^children_spec:\s*$", stripped):
            in_block = True
            continue
        if not in_block:
            continue
        item_start = re.match(r"^\s*-\s+id:\s*(.+)$", raw)
        if item_start:
            if current:
                entries.append(current)
            current = {"id": _strip_quotes(item_start.group(1).strip())}
            continue
        if current is None:
            if FRONTMATTER_KV_RE.match(raw):
                in_block = False
            continue
        matched_field = False
        for key in CHILDREN_SPEC_ITEM_KEYS[1:]:
            field_match = re.match(rf"^\s+{key}:\s*(.+)$", raw)
            if field_match:
                current[key] = _strip_quotes(field_match.group(1).strip())
                matched_field = True
                break
        if not matched_field and FRONTMATTER_KV_RE.match(raw):
            in_block = False
            if current:
                entries.append(current)
                current = None
    if current:
        entries.append(current)
    return entries


def parse_frontmatter_todos(text: str) -> list[dict[str, str]]:
    """Parse structured ``todos:`` entries from plan frontmatter."""
    fm_lines: list[str] = []
    pos = 0
    while pos < len(text):
        match = FRONTMATTER_BLOCK_RE.match(text[pos:])
        if not match:
            break
        fm_lines.extend(match.group(1).splitlines())
        pos += match.end()
        remainder = text[pos:].lstrip("\n")
        if remainder.startswith("---"):
            pos = len(text) - len(remainder)
            continue
        break
    if not fm_lines:
        return []
    todos: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    in_todos = False
    for raw in fm_lines:
        stripped = raw.strip()
        if not stripped:
            continue
        if re.match(r"^todos:\s*$", stripped):
            in_todos = True
            continue
        if not in_todos:
            continue
        item_start = re.match(r"^\s*-\s+id:\s*(.+)$", raw)
        if item_start:
            if current:
                todos.append(current)
            current = {
                "id": _strip_quotes(item_start.group(1).strip()),
                "content": "",
                "status": "pending",
            }
            continue
        if current is None:
            if FRONTMATTER_KV_RE.match(raw):
                in_todos = False
            continue
        content_match = re.match(r"^\s+content:\s*(.+)$", raw)
        if content_match:
            current["content"] = _strip_quotes(content_match.group(1).strip())
            continue
        status_match = re.match(r"^\s+status:\s*(.+)$", raw)
        if status_match:
            current["status"] = _strip_quotes(status_match.group(1).strip()).lower()
            continue
        if FRONTMATTER_KV_RE.match(raw):
            in_todos = False
            if current:
                todos.append(current)
                current = None
    if current:
        todos.append(current)
    return todos


def render_frontmatter_todos(todos: list[dict[str, str]]) -> list[str]:
    lines = ["todos:"]
    for todo in todos:
        lines.append(f"  - id: {todo.get('id', '')}")
        content = str(todo.get("content") or "").replace('"', '\\"')
        lines.append(f'    content: "{content}"')
        lines.append(f"    status: {todo.get('status', 'pending')}")
    return lines


def slice_body_section(body: str, section_anchor: str) -> str:
    """Extract markdown body from ``section_anchor`` until the next H2 or EOF."""
    anchor = section_anchor.strip()
    if not anchor.startswith("#"):
        anchor = section_anchor.lstrip("#").strip()
        anchor = f"## {anchor}" if anchor else ""
    if not anchor:
        return ""
    lines = body.splitlines()
    start_idx: int | None = None
    for idx, line in enumerate(lines):
        if line.strip() == anchor or line.strip().startswith(anchor):
            start_idx = idx
            break
    if start_idx is None:
        return ""
    end_idx = len(lines)
    for idx in range(start_idx + 1, len(lines)):
        if lines[idx].startswith("## "):
            end_idx = idx
            break
    return "\n".join(lines[start_idx:end_idx]).strip() + "\n"


def plan_lookup_roots(repo_root: Path, plans_root: Path | None = None) -> list[Path]:
    """Directories a relative plan argument may be resolved against, in priority order."""
    roots: list[Path] = []

    def _add(candidate: Path) -> None:
        resolved = candidate.expanduser().resolve()
        if resolved not in roots:
            roots.append(resolved)

    if plans_root is not None:
        _add(Path(plans_root))
    repo = Path(repo_root).expanduser().resolve()
    _add(repo)
    _add(Path.cwd())
    for ancestor in list(repo.parents)[:PLAN_LOOKUP_ANCESTOR_DEPTH]:
        _add(ancestor)
    return roots


def resolve_plan_path(
    plan_arg: Path | str,
    repo_root: Path,
    plans_root: Path | None = None,
) -> Path:
    """
    Resolve a plan argument that may be absolute, plans-root relative, repo relative,
    or relative to the workspace above the code repo.

    Plans and code do not always share a repo: a workspace can keep `.cursor/plans/`
    at its root while code lives in nested repos.
    """
    arg = Path(plan_arg).expanduser()
    if arg.is_absolute():
        return arg.resolve()
    roots = plan_lookup_roots(repo_root, plans_root)
    for root in roots:
        candidate = root / arg
        if candidate.is_file():
            return candidate.resolve()
    return (roots[0] / arg).resolve()


def plan_is_inside_repo(plan_path: Path, repo_root: Path) -> bool:
    try:
        Path(plan_path).resolve().relative_to(Path(repo_root).expanduser().resolve())
    except ValueError:
        return False
    return True


def relative_plan_source(plan_path: Path, repo_root: Path) -> str:
    """
    Plan identity relative to ``repo_root``, tolerating plans stored outside the repo.

    Returns a repo-relative posix path when possible, otherwise a ``../`` relative
    path, falling back to the absolute path when no relative path exists.
    """
    plan = Path(plan_path).expanduser().resolve()
    root = Path(repo_root).expanduser().resolve()
    try:
        return plan.relative_to(root).as_posix()
    except ValueError:
        pass
    try:
        return Path(os.path.relpath(plan, root)).as_posix()
    except ValueError:
        return plan.as_posix()


def plan_in_ide_plans_dir(plan_path: Path) -> bool:
    """True for `<ide-dir>/plans/*.plan.md` (for example `.cursor/plans/`, `.codex/plans/`)."""
    parent = Path(plan_path).expanduser().resolve().parent
    return parent.name == "plans" and parent.parent.name.startswith(".")


def parse_plan_disposition(plan_path: Path) -> str:
    fm = parse_plan_frontmatter(plan_path)
    return str(fm.get("disposition") or "active").strip()


def resolve_plan_branch(plan_path: Path) -> str:
    """Frontmatter ``branch:`` wins; else inferred slug branch."""
    fm = parse_plan_frontmatter(plan_path)
    explicit = str(fm.get("branch") or "").strip()
    if explicit:
        return explicit
    return branch_name_for_plan(plan_path)


def is_meta_plan(plan_path: Path) -> bool:
    return parse_plan_disposition(plan_path) == "meta"


def meta_slug_from_path(plan_path: Path) -> str:
    stem = plan_path.stem
    if stem.endswith(".plan"):
        stem = stem[: -len(".plan")]
    return stem


def plan_type_from_text(head: str) -> str:
    """Infer branch prefix from plan title/body head (mirrors on-stop-gitops-plans.sh)."""
    lower = head[:2000].lower()
    if re.search(r"\bbugfix\b|\bbug\b|\bfix\b", lower):
        return "bugfix"
    if re.search(r"\bhotfix\b|\bhot\b", lower):
        return "hotfix"
    if re.search(r"\bchore\b|\bmaintenance\b|\bdependenc", lower):
        return "chore"
    if re.search(r"\brefactor\b", lower):
        return "refactor"
    if re.search(r"\bdocs\b|\bdocumentation\b", lower):
        return "docs"
    return "feature"


def slug_from_plan_path(plan_path: Path) -> str:
    text = plan_path.read_text(encoding="utf-8", errors="ignore")
    for line in text.splitlines():
        if line.startswith("# "):
            raw = line[2:].strip()
            break
    else:
        raw = plan_path.stem.replace(".plan", "")
    slug = re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")
    slug = re.sub(r"-+", "-", slug)
    return (slug or "plan")[:40]


def branch_name_for_plan(plan_path: Path, *, plan_type: str | None = None) -> str:
    ptype = plan_type or plan_type_from_text(
        plan_path.read_text(encoding="utf-8", errors="ignore")[:2000]
    )
    slug = slug_from_plan_path(plan_path)
    return f"{ptype}/{slug}"


def _ref_exists(repo_root: Path, ref: str) -> bool:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_root), "show-ref", "--verify", "--quiet", ref],
            capture_output=True,
            check=False,
        )
        return proc.returncode == 0
    except OSError:
        return False


def is_git_repo(repo_root: Path) -> bool:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--git-dir"],
            capture_output=True,
            text=True,
            check=False,
        )
        return proc.returncode == 0
    except OSError:
        return False


def origin_default_branch(repo_root: Path) -> str:
    """Default branch name from `refs/remotes/origin/HEAD`, or empty when unset."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_root), "symbolic-ref", "refs/remotes/origin/HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return ""
    ref = (proc.stdout or "").strip()
    if proc.returncode != 0 or not ref.startswith("refs/remotes/origin/"):
        return ""
    return ref[len("refs/remotes/origin/") :]


def plan_base_branch_override(plan_path: Path) -> str:
    """Explicit base branch from plan frontmatter (`base_branch:`, `baseBranch:`, `base:`)."""
    fm = parse_plan_frontmatter(plan_path)
    for key in BASE_BRANCH_FRONTMATTER_KEYS:
        value = str(fm.get(key) or "").strip()
        if value:
            return value
    return ""


def resolve_base_branch(repo_root: Path, override: str | None = None) -> str:
    """
    Branch to create plan branches from.

    Priority: explicit override → `origin/HEAD` default → conventional local branches →
    current branch. Remote-tracking form (`origin/<name>`) is returned when only the
    remote branch exists, so `git branch` still works in a fresh clone.
    """
    explicit = (override or "").strip()
    if explicit:
        return explicit

    candidates: list[str] = []
    default = origin_default_branch(repo_root)
    if default:
        candidates.append(default)
    candidates.extend(name for name in BASE_BRANCH_CANDIDATES if name not in candidates)

    for name in candidates:
        if branch_ref_exists(repo_root, name):
            return name
    for name in candidates:
        if _ref_exists(repo_root, f"refs/remotes/origin/{name}"):
            return f"origin/{name}"
    return current_branch(repo_root) or "main"


def resolve_plan_base_branch(
    plan_path: Path,
    repo_root: Path,
    override: str | None = None,
) -> str:
    """Base branch for one plan: CLI override → plan frontmatter → repo default."""
    explicit = (override or "").strip() or plan_base_branch_override(plan_path)
    return resolve_base_branch(repo_root, explicit or None)


def branch_ref_exists(repo_root: Path, branch: str) -> bool:
    return _ref_exists(repo_root, f"refs/heads/{branch}")


def create_branch_ref(repo_root: Path, branch: str, base_branch: str) -> tuple[bool, str]:
    """Create local branch without checkout. Returns (ok, message)."""
    if branch_ref_exists(repo_root, branch):
        return True, "already_exists"
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_root), "branch", branch, base_branch],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        return False, str(exc)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        return False, err or f"git branch failed ({proc.returncode})"
    return True, "created"


def current_branch(repo_root: Path) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_root), "branch", "--show-current"],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 0:
            return (proc.stdout or "").strip()
    except OSError:
        pass
    return ""


def working_tree_dirty(repo_root: Path) -> bool:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_root), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=False,
        )
        return proc.returncode == 0 and bool((proc.stdout or "").strip())
    except OSError:
        return False


def checkout_plan_branch(
    repo_root: Path,
    branch: str,
    *,
    plan_slug: str = "plan",
    allow_stash: bool = True,
) -> dict[str, object]:
    """
    Switch to plan branch (plan-execution policy).
    Stashes dirty tree when allow_stash=True; does not pop stash (caller/agent continues work).
    """
    result: dict[str, object] = {
        "ok": False,
        "branch": branch,
        "previous_branch": current_branch(repo_root),
        "stashed": False,
        "stash_ref": "",
        "message": "",
    }
    if not branch_ref_exists(repo_root, branch):
        result["message"] = f"branch not found: {branch}"
        return result
    current = str(result["previous_branch"])
    if current == branch:
        result["ok"] = True
        result["message"] = "already_on_branch"
        return result
    if working_tree_dirty(repo_root) and allow_stash:
        msg = f"braindrain plan-execution {plan_slug}"
        try:
            proc = subprocess.run(
                ["git", "-C", str(repo_root), "stash", "push", "-u", "-m", msg],
                capture_output=True,
                text=True,
                check=False,
            )
            if proc.returncode == 0:
                result["stashed"] = True
                result["stash_ref"] = "stash@{0}"
        except OSError as exc:
            result["message"] = f"stash failed: {exc}"
            return result
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_root), "switch", branch],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        result["message"] = str(exc)
        return result
    if proc.returncode != 0:
        result["message"] = (proc.stderr or proc.stdout or "").strip()
        return result
    result["ok"] = True
    result["message"] = "switched"
    return result
