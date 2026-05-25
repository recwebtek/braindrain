import type { ChipTone, DashboardTab } from "@/data";

// Brand Color Palette - Purple/Fuchsia Accent System
export const brandColors = {
  50: "var(--ld-brand-50)",
  100: "var(--ld-brand-100)",
  200: "var(--ld-brand-200)",
  300: "var(--ld-brand-300)",
  400: "var(--ld-brand-400)",
  500: "var(--ld-brand-500)",
  600: "var(--ld-brand-600)",
  700: "var(--ld-brand-700)",
  800: "var(--ld-brand-800)",
  900: "var(--ld-brand-900)",
  950: "var(--ld-brand-950)",
} as const;

// Neon Glow Values
export const neonGlow = {
  purple: "var(--neon-purple)",
  purpleSoft: "var(--neon-purple-soft)",
  pink: "var(--neon-pink)",
  pinkSoft: "var(--neon-pink-soft)",
  cyan: "var(--neon-cyan)",
} as const;

// Glow Shadow Presets
export const glowShadows = {
  sm: "var(--glow-purple-sm)",
  md: "var(--glow-purple-md)",
  lg: "var(--glow-purple-lg)",
  border: "var(--glow-border-purple)",
} as const;

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

// Brand-accented tone variants with purple glow
export const toneClassNamesBrand: Record<ChipTone, string> = {
  blue: "bg-[color:var(--ld-tone-blue-bg)] text-[color:var(--ld-tone-blue-fg)] ring-1 ring-[color:var(--ld-brand-500)]/30",
  cyan: "bg-[color:var(--ld-tone-cyan-bg)] text-[color:var(--ld-tone-cyan-fg)] ring-1 ring-[color:var(--ld-brand-500)]/30",
  emerald:
    "bg-[color:var(--ld-tone-emerald-bg)] text-[color:var(--ld-tone-emerald-fg)] ring-1 ring-[color:var(--ld-brand-500)]/30",
  amber: "bg-[color:var(--ld-tone-amber-bg)] text-[color:var(--ld-tone-amber-fg)] ring-1 ring-[color:var(--ld-brand-500)]/30",
  violet:
    "bg-[color:var(--ld-tone-violet-bg)] text-[color:var(--ld-brand-300)] ring-1 ring-[color:var(--ld-brand-500)]/50 shadow-[0_0_15px_rgba(168,85,247,0.2)]",
  rose: "bg-[color:var(--ld-tone-rose-bg)] text-[color:var(--ld-tone-rose-fg)] ring-1 ring-[color:var(--ld-brand-500)]/30",
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
