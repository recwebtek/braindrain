# GitOps Skill

## When to Apply
Apply when executing any git operation — branch creation, staging, committing, worktree management, merge-all, PR prep, or CI checks.

## Startup Checklist (run before every invocation)

```
[ ] Read .cursor/.gitops-memory.jsonl (last 20 lines) — note relevant past errors
[ ] Read .cursor/.gitops-queue.json — check for pending branch-setup entries
[ ] Run git status — verify working state
[ ] Confirm operation mode matches the task (branch-setup / commit / merge-all / pr-create / status-check)
```

## Safety Checklist (run before every write operation)

```
[ ] Is git status clean or are staged files intentional?
[ ] Are all files in the commit explicitly listed in the task spec?
[ ] Is this a protected branch (main/master)? If yes, STOP.
[ ] Am I about to checkout/switch branches during branch-setup? If yes, STOP — use git branch only.
[ ] Has CI passed on this branch? (required before push)
[ ] Is the branch name correct for the task type? (feature/ bugfix/ hotfix/ chore/ refactor/ docs/)
```

## Commit Message Convention

```
<type>(<scope>): <description> [T<NNN>]

Types: feat | fix | chore | docs | style | refactor | test | ci
Scope: component name, module, or file area
Max 72 chars on subject line
```

Examples:
- `feat(auth): add JWT refresh endpoint [T014]`
- `chore(config): add tailwind safelist for dynamic classes [T007]`
- `test(blog): add slug validation unit tests [T022]`

## Branch Naming Convention

```
feature/<slug>     ← new functionality
bugfix/<slug>      ← bug corrections
hotfix/<slug>      ← urgent production fixes
chore/<slug>       ← maintenance, deps, config
refactor/<slug>    ← restructuring without behaviour change
docs/<slug>        ← documentation only
merge/<date>       ← merge-all output branch (e.g. merge/sprint-2026-04-05)
```

## Worktree Naming Convention (Phase 3 — deferred)

```
../[project-name]-stage-[N]        ← worktree directory
feature/stage-[N]-[short-desc]     ← branch name
```

## Branch Creation Rule

**NEVER** use `git checkout -b` or `git switch -c` for branch-setup mode.
Always use `git branch <name> <base>` which creates without switching.
Verify with `git branch --show-current` that HEAD is unchanged after creation.

Exception: `merge-all` mode creates and checks out the merge branch, then
restores the original branch with `git checkout -` when done.

## Push Rules

1. Run `git diff --stat origin/<branch>` first — confirm what's going up
2. Only push to the feature or merge branch — never to main
3. If branch doesn't exist on remote: `git push -u origin <branch>`
4. If it does: `git push origin <branch>`

## `gh` CLI Discipline

Always use `--json` + `--jq` to limit output:
```bash
gh pr view --json title,state,mergeable --jq '{title,state,mergeable}'
gh pr list --json number,title,headRefName --jq '.[] | {number,title}'
gh pr checks --json name,status,conclusion --jq '.[] | select(.conclusion != "success")'
```
Never run `gh pr list` or `gh issue list` without `--jq` field selection.

## Merge-All Checklist

```
[ ] Confirm featureBranches list is complete and correct
[ ] Confirm targetMergeBranch name follows merge/<date-or-sprint> convention
[ ] Confirm baseBranch exists and is up to date
[ ] For each branch: check commit count (git rev-list --count base..branch)
[ ] Apply squash if >3 commits, merge --no-ff if <=3 commits
[ ] On any conflict: git merge --abort, report conflictFiles, HALT
[ ] After all branches merged: push merge branch
[ ] Create PR with gh pr create --json url --jq '.url'
[ ] Return to original branch with git checkout -
```

## Merge PR Prep Steps

```bash
git log --oneline main..HEAD        # list commits
git diff --stat main..HEAD          # file changes
git log --format="- %s" main..HEAD  # commit messages for PR body
```

## Memory Protocol

- **Read**: `.cursor/.gitops-memory.jsonl` on every startup (last 20 entries)
- **Append**: Only when a previous failure is resolved in a subsequent invocation
- **Format**: `{"ts":"ISO8601","operation":"...","error":"...","resolution":"...","branchContext":"..."}`
- **Prune**: Never auto-prune. Recommend pruning (include `memoryPruneRecommended: true` in response) if >100 entries.

## Recovery Procedures

| Situation | Command |
|-----------|---------|
| Committed to wrong branch | `git reset --soft HEAD~1` then re-commit on correct branch |
| Staged wrong file | `git restore --staged <file>` |
| Need to undo last commit | `git reset --soft HEAD~1` |
| Detached HEAD | `git checkout <branch-name>` |
| Mid-merge conflict | `git merge --abort` then report to coordinator |
| **Merge conflict** | HALT — surface to coordinator with `conflictFiles` list |
| **Protected branch write** | HALT — report and refuse |
| **Wrong branch on startup** | Verify only, do not auto-switch — inform coordinator |

## Escalation Chain

```
gitops (failure) → coordinator (analyzes + checks memory) → user (decides)
                       ↓ if known fix from memory
                   gitops retry (success → append to memory)
```
