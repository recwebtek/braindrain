import type { ChipTone, DashboardTab } from "@/data";

export const toneClassNames: Record<ChipTone, string> = {
  blue: "bg-[color:var(--ld-tone-blue-bg)] text-[color:var(--ld-tone-blue-fg)] ring-1 ring-[color:var(--ld-tone-blue-ring)]",
  cyan: "bg-[color:var(--ld-tone-cyan-bg)] text-[color:var(--ld-tone-cyan-fg)] ring-1 ring-[color:var(--ld-tone-cyan-ring)]",
  emerald:
    "bg-[color:var(--ld-tone-emerald-bg)] text-[color:var(--ld-tone-emerald-fg)] ring-1 ring-[color:var(--ld-tone-emerald-ring)]",
  amber: "bg-[color:var(--ld-tone-amber-bg)] text-[color:var(--ld-tone-amber-fg)] ring-1 ring-[color:var(--ld-tone-amber-ring)]",
  violet:
    "bg-[color:var(--ld-tone-violet-bg)] text-[color:var(--ld-tone-violet-fg)] ring-1 ring-[color:var(--ld-tone-violet-ring)]",
  rose: "bg-[color:var(--ld-tone-rose-bg)] text-[color:var(--ld-tone-rose-fg)] ring-1 ring-[color:var(--ld-tone-rose-ring)]",
};

export function toneClass(tone: ChipTone) {
  return toneClassNames[tone] ?? toneClassNames.violet;
}

export const dashboardTabs: Array<{ id: DashboardTab; label: string; detail: string; group: string }> = [
  { id: "overview", label: "Overview", detail: "Repo summary and active signals", group: "Workspace" },
  { id: "commands", label: "Commands", detail: "Approved command presets", group: "Workspace" },
  { id: "git", label: "Git", detail: "Branch drift and guarded sync", group: "Workspace" },
  { id: "processes", label: "Processes", detail: "Repo-scoped services", group: "Workspace" },
  { id: "tests", label: "Tests", detail: "Project and CI test inventory", group: "Workspace" },
  { id: "braindrain_logs", label: "Logs", detail: "MCP observer and session logs", group: "Braindrain" },
  { id: "primer", label: "Primer", detail: "Dotfiles and last primed state", group: "Braindrain" },
  { id: "config", label: "Config", detail: "Read-only hub and memory viewer", group: "Braindrain" },
  { id: "agents", label: "Agents", detail: "Installed agents and hooks", group: "Braindrain" },
  { id: "skills", label: "Skills", detail: "Installed skills and template drift", group: "Braindrain" },
  { id: "plans", label: "Plans", detail: "Master plan and next-actions", group: "Braindrain" },
  { id: "telemetry", label: "Telemetry", detail: "Runtime signals and exports", group: "Signals" },
];
