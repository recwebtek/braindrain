---
name: Multi-feature umbrella (meta)
overview: "Umbrella meta-plan for N features — do not Build directly; run /metaplan-closeout then Build child plans."
disposition: meta
owner: @handle
dri: @handle
children_spec:
  - id: feature-a
    file: project-feature-a.plan.md
    name: "Feature A title"
    branch: feature/feature-a-slug
    section: "## 1. Feature A"
  - id: feature-b
    file: project-feature-b.plan.md
    name: "Feature B title"
    branch: feature/feature-b-slug
    section: "## 2. Feature B"
todos:
  - id: split-feature-a
    content: "Child plan project-feature-a.plan.md exists with implementation todos"
    status: pending
  - id: split-feature-b
    content: "Child plan project-feature-b.plan.md exists with implementation todos"
    status: pending
isProject: false
---

# Multi-feature umbrella

Author feature sections below. Each `section:` in `children_spec` maps to an H2 heading; `/metaplan-closeout` slices from that heading until the next H2.

## 1. Feature A

_Details for feature A._

## 2. Feature B

_Details for feature B._

## Workflow

1. Planning mode: author this meta plan with `children_spec`
2. `/metaplan-closeout` → child skeletons + `_master` links
3. Agent phase 2: extract bodies into children (if `body_pending`)
4. `/masterplan` → build queue
5. Plan Build on **one child** plan at a time
