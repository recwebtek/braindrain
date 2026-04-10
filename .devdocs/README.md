# .devdocs — ship-tracked notes

This directory holds **versioned** planning and ops notes that should ride with the repo. It is **not** a substitute for machine-local memory:

- **Durable, private memory** lives under `.braindrain/` (gitignored). `prime_workspace()` migrates legacy `.devdocs/` memory files into `.braindrain/` on first run.
- **This folder** is for roadmap, release-facing TODOs, and pointers that contributors and agents should see in git.

## Index

| File | Purpose |
|------|---------|
| [ROADMAP.md](./ROADMAP.md) | Near-term product and platform direction |
| [TODOS.md](./TODOS.md) | Actionable checklist aligned with the current release |

When you cut a release, update `VERSION`, `CHANGELOG.md`, and `README.md` together, then refresh the roadmap/TODOs here so they match reality.
