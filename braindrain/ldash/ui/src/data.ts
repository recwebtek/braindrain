export type ChipTone = "blue" | "cyan" | "emerald" | "amber" | "violet" | "rose";

export type DashboardTab =
  | "overview"
  | "commands"
  | "git"
  | "processes"
  | "telemetry"
  | "braindrain_logs"
  | "primer"
  | "config"
  | "agents"
  | "skills"
  | "plans"
  | "tests";

export const tabPaths: Record<DashboardTab, string> = {
  overview: "/",
  commands: "/commands",
  git: "/git",
  processes: "/processes",
  telemetry: "/telemetry",
  braindrain_logs: "/braindrain/logs",
  primer: "/primer",
  config: "/config",
  agents: "/agents",
  skills: "/skills",
  plans: "/plans",
  tests: "/tests",
};

export function tabFromPath(pathname: string): DashboardTab {
  const entry = Object.entries(tabPaths).find(([, path]) => path === pathname);
  return (entry?.[0] as DashboardTab) ?? "overview";
}

export interface FactChip {
  label: string;
  value: string;
  tone: ChipTone;
}

export interface SpineItem {
  label: string;
  value: string;
  tone: ChipTone;
  detail: string;
}

export interface StartupStep {
  label: string;
  detail: string;
  tone: ChipTone;
}

export interface OverviewShortcut {
  id: DashboardTab | "plans" | "tests";
  label: string;
  detail: string;
  tone: ChipTone;
}

export interface AgentRecord {
  name: string;
  provider: string;
  path: string;
  model?: string | null;
  description?: string;
  tier?: string | null;
  hooks?: string[];
  template_match?: boolean;
  installed?: boolean;
}

export interface AgentsContract {
  version: string;
  count: number;
  template_count: number;
  items: AgentRecord[];
  updated_at: string;
}

export interface SkillsContract {
  version: string;
  installed_count: number;
  template_count: number;
  drift_missing: string[];
  installed: Array<{ name: string; path: string; excerpt: string }>;
  templates: Array<{ name: string; path: string; excerpt: string }>;
  updated_at: string;
}

export interface PrimerContract {
  version: string;
  primer: {
    last_primed_at?: string;
    bundle?: string;
    dotfiles?: Array<{ name: string; exists: boolean }>;
  };
  env_context?: Record<string, unknown>;
  updated_at: string;
}

export interface ConfigPageContract {
  version: string;
  read_only: boolean;
  hub_config: { tree?: Record<string, unknown> };
  memory: { files?: Record<string, { excerpt: string; exists?: boolean }> };
  updated_at: string;
}

export interface BraindrainLogsContract {
  version: string;
  observer?: { stats?: Record<string, unknown>; events?: Array<Record<string, unknown>> };
  session_jsonl?: { recent_events?: Array<Record<string, unknown>> };
  token_checkpoints?: Array<Record<string, unknown>>;
  updated_at?: string;
}

export interface CursorPlanRecord {
  path: string;
  name: string;
  disposition: string;
  priority?: string | number | null;
  branch?: string | null;
  archived?: boolean;
  modified_at?: string;
  excerpt?: string;
}

export interface PlansContract {
  version: string;
  master_plan?: { excerpt?: string; exists?: boolean };
  next_actions?: { excerpt?: string; items?: Array<{ verb: string; plan_id: string }> };
  audit_files?: string[];
  cursor_plans?: CursorPlanRecord[];
  updated_at: string;
}

export interface TestsContract {
  version: string;
  python_tests: string[];
  python_test_count: number;
  scripts: Array<{ id: string; label: string; command: string; cwd?: string }>;
  ci_workflows: Array<{ file: string; jobs: string[] }>;
  updated_at: string;
}

export interface OverviewMetric {
  label: string;
  value: string;
  tone: ChipTone;
}

export interface OverviewActivity {
  label: string;
  detail: string;
  tone: ChipTone;
}

export interface OverviewContract {
  version: string;
  workspace: {
    name: string;
    project_name: string;
    branch: string;
  };
  repo_brief: {
    title: string;
    summary: string;
    entrypoint: string;
    posture: string;
  };
  facts: FactChip[];
  systems: SpineItem[];
  startup_flow: StartupStep[];
  kpis: OverviewMetric[];
  recent_activity: OverviewActivity[];
  shortcuts: OverviewShortcut[];
  map_access: {
    label: string;
    description: string;
    cta: string;
  };
  updated_at: string;
}

export interface CommandCatalogItem {
  id: string;
  label: string;
  description: string;
  cwd: string;
  timeout_seconds: number;
}

export interface CommandCatalogGroup {
  id: string;
  label: string;
  items: CommandCatalogItem[];
}

export interface CommandRunEntry {
  id: string;
  label: string;
  category: string;
  cwd: string;
  ok: boolean;
  status: string;
  returncode: number;
  duration_ms: number;
  stdout: string;
  stderr: string;
  finished_at: string;
}

export interface CommandsContract {
  version: string;
  groups: CommandCatalogGroup[];
  history: CommandRunEntry[];
  updated_at: string;
}

export interface GitCommit {
  hash: string;
  subject: string;
  age: string;
}

export interface GitContract {
  version: string;
  summary: {
    branch: string;
    dirty: boolean;
    ahead: number;
    behind: number;
    staged: number;
    unstaged: number;
    untracked: number;
    recent_commits: GitCommit[];
    last_checked_at: string;
  };
  actions: Array<{
    id: string;
    label: string;
    description: string;
  }>;
  updated_at: string;
}

export interface ServiceEntry {
  id: string;
  name: string;
  description: string;
  cwd: string;
  allowed_actions: string[];
  status: string;
  healthy: boolean;
  pid: number | null;
  open_target?: string | null;
  healthcheck_url?: string | null;
  last_started_at?: string | null;
  last_stopped_at?: string | null;
  last_exit_code?: number | null;
}

export interface ProcessesContract {
  version: string;
  items: ServiceEntry[];
  updated_at: string;
}

export interface TelemetryEvent {
  kind: string;
  label: string;
  status: string;
  detail: string;
  time: string;
}

export interface TelemetryContract {
  version: string;
  summary: {
    active_tools: number;
    agents_online: number;
    refresh_age_seconds: number;
    token_saving_active: boolean;
    env_drift: number;
    recent_action_count: number;
  };
  events: TelemetryEvent[];
  updated_at: string;
}

export interface ActionEnvelope<T> {
  ok: boolean;
  status: string;
  message: string;
  updated_at: string;
  command_run?: T;
  git_action?: T;
  service?: T;
}

export const fallbackOverview: OverviewContract = {
  version: "1.0",
  workspace: {
    name: "BRAIN_MCP_HUB",
    project_name: "LivingDash",
    branch: "main",
  },
  repo_brief: {
    title: "Workspace overview",
    summary: "Local operator shell for repo state, guarded commands, repo-scoped services, and telemetry.",
    entrypoint: "braindrain/server.py",
    posture: "Operational shell with guarded local actions",
  },
  facts: [
    { label: "Workspace", value: "BRAIN_MCP_HUB", tone: "violet" },
    { label: "Project", value: "LivingDash", tone: "cyan" },
    { label: "Branch", value: "main", tone: "emerald" },
    { label: "Dirty", value: "No", tone: "emerald" },
    { label: "Tools", value: "4", tone: "violet" },
  ],
  systems: [
    { label: "Git", value: "clean", tone: "emerald", detail: "ahead 0 · behind 0" },
    { label: "Processes", value: "1", tone: "cyan", detail: "Repo-scoped services available to the dashboard." },
    { label: "Telemetry", value: "active", tone: "violet", detail: "refresh age 15s" },
  ],
  startup_flow: [
    { label: "Load snapshot", detail: "Gather current workspace state.", tone: "cyan" },
    { label: "Refresh modules", detail: "Overlay git, service, and telemetry signals.", tone: "violet" },
    { label: "Open shell", detail: "Keep overview visible while deeper tabs load.", tone: "emerald" },
  ],
  kpis: [
    { label: "Commands run", value: "3", tone: "violet" },
    { label: "Services running", value: "1", tone: "cyan" },
    { label: "Git changes", value: "0", tone: "amber" },
    { label: "Active MCP tools", value: "4", tone: "emerald" },
  ],
  recent_activity: [
    { label: "Run UI tests", detail: "success · exit 0", tone: "emerald" },
    { label: "Build UI bundle", detail: "success · exit 0", tone: "cyan" },
  ],
  shortcuts: [
    { id: "commands", label: "Open commands", detail: "Run approved workspace commands.", tone: "violet" },
    { id: "git", label: "Open git status", detail: "Inspect branch drift and guarded sync actions.", tone: "cyan" },
    { id: "processes", label: "Open processes", detail: "Manage repo-scoped services only.", tone: "amber" },
    { id: "telemetry", label: "Open telemetry", detail: "Inspect recent runtime signals and exports.", tone: "emerald" },
  ],
  map_access: {
    label: "Map access",
    description: "The bounded systems map remains a secondary drill-down, not the primary workspace.",
    cta: "OPEN SYSTEM MAP",
  },
  updated_at: "just now",
};

export const fallbackCommands: CommandsContract = {
  version: "1.0",
  groups: [
    {
      id: "quality",
      label: "Quality",
      items: [
        {
          id: "ui_tests",
          label: "Run UI tests",
          description: "Run the LivingDash Vitest suite.",
          cwd: "braindrain/ldash/ui",
          timeout_seconds: 180,
        },
      ],
    },
  ],
  history: [],
  updated_at: "just now",
};

export const fallbackGit: GitContract = {
  version: "1.0",
  summary: {
    branch: "main",
    dirty: false,
    ahead: 0,
    behind: 0,
    staged: 0,
    unstaged: 0,
    untracked: 0,
    recent_commits: [
      { hash: "abc1234", subject: "Seed dashboard MVP", age: "just now" },
      { hash: "def5678", subject: "Refine sidecar contracts", age: "2 hours ago" },
    ],
    last_checked_at: "just now",
  },
  actions: [
    { id: "fetch", label: "Fetch", description: "Run git fetch --all --prune." },
    { id: "pull", label: "Pull", description: "Run git pull --ff-only on the current branch." },
  ],
  updated_at: "just now",
};

export const fallbackProcesses: ProcessesContract = {
  version: "1.0",
  items: [
    {
      id: "ui_preview",
      name: "UI Preview",
      description: "Launch the Vite preview server for the dashboard UI.",
      cwd: "braindrain/ldash/ui",
      allowed_actions: ["start", "stop", "open"],
      status: "stopped",
      healthy: false,
      pid: null,
      open_target: "http://127.0.0.1:4173",
    },
  ],
  updated_at: "just now",
};

export const fallbackTelemetry: TelemetryContract = {
  version: "1.0",
  summary: {
    active_tools: 4,
    agents_online: 2,
    refresh_age_seconds: 15,
    token_saving_active: true,
    env_drift: 0,
    recent_action_count: 2,
  },
  events: [
    {
      kind: "command",
      label: "Run UI tests",
      status: "success",
      detail: "exit 0 in 1834ms",
      time: "just now",
    },
  ],
  updated_at: "just now",
};
