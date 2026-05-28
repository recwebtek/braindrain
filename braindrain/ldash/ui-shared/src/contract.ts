export const LIVINGDASH_CONTRACT_VERSION = "2.1";

export type Tone = "blue" | "cyan" | "emerald" | "amber" | "violet" | "rose";

export interface VersionedPayload {
  version: string;
  updated_at?: string;
}

export interface ActionEnvelope<T = Record<string, unknown>> {
  ok: boolean;
  status: string;
  message: string;
  updated_at: string;
  command_run?: T;
  git_action?: T;
  service?: T;
}

export interface AuthSession {
  authenticated: boolean;
  userName?: string;
  username?: string;
}

export interface LoginPayload {
  username: string;
  password: string;
}

export interface OverviewContract extends VersionedPayload {
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
  facts: Array<{ label: string; value: string; tone: Tone }>;
  systems: Array<{ label: string; value: string; tone: Tone; detail: string }>;
  startup_flow: Array<{ label: string; detail: string; tone: Tone }>;
  kpis: Array<{ label: string; value: string; tone: Tone }>;
  recent_activity: Array<{ label: string; detail: string; tone: Tone }>;
  shortcuts: Array<{ id: string; label: string; detail: string; tone: Tone }>;
  map_access: {
    label: string;
    description: string;
    cta: string;
  };
}

export interface CommandsContract extends VersionedPayload {
  groups: Array<{
    id: string;
    label: string;
    items: Array<{
      id: string;
      label: string;
      description: string;
      cwd: string;
      timeout_seconds: number;
    }>;
  }>;
  history: Array<Record<string, unknown>>;
}

export interface GitContract extends VersionedPayload {
  summary: {
    branch: string;
    dirty: boolean;
    ahead: number;
    behind: number;
    staged: number;
    unstaged: number;
    untracked: number;
    recent_commits: Array<{ hash: string; subject: string; age: string }>;
    last_checked_at: string;
  };
  actions: Array<{ id: string; label: string; description: string }>;
}

export interface ProcessesContract extends VersionedPayload {
  items: Array<{
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
  }>;
}

export interface TelemetryContract extends VersionedPayload {
  summary: {
    active_tools: number;
    agents_online: number;
    refresh_age_seconds: number;
    token_saving_active: boolean;
    env_drift: number;
    recent_action_count: number;
    session_events?: number;
    tokens_saved_total?: number;
  };
  events: Array<Record<string, unknown>>;
  file_telemetry?: Record<string, unknown>;
  observer_stats?: Record<string, unknown>;
}

export interface AgentsContract extends VersionedPayload {
  count: number;
  template_count?: number;
  items: Array<Record<string, unknown>>;
}

export interface SkillsContract extends VersionedPayload {
  installed_count: number;
  template_count: number;
  drift_missing: string[];
  installed: Array<Record<string, unknown>>;
  templates: Array<Record<string, unknown>>;
}

export interface PlansContract extends VersionedPayload {
  cursor_plans?: Array<Record<string, unknown>>;
  next_actions?: Record<string, unknown>;
  master_plan?: Record<string, unknown>;
  audit_files?: string[];
}

export interface TestsContract extends VersionedPayload {
  python_tests: string[];
  python_test_count: number;
  scripts: Array<Record<string, unknown>>;
  ci_workflows: Array<Record<string, unknown>>;
}

export interface PrimerContract extends VersionedPayload {
  primer: Record<string, unknown>;
  env_context?: Record<string, unknown>;
}

export interface ConfigPageContract extends VersionedPayload {
  read_only: boolean;
  hub_config: Record<string, unknown>;
  memory: Record<string, unknown>;
}

export interface BraindrainLogsContract extends VersionedPayload {
  observer?: Record<string, unknown>;
  session_jsonl?: Record<string, unknown>;
  token_checkpoints?: Array<Record<string, unknown>>;
}

export interface GitopsContract extends VersionedPayload {
  queue_path?: string;
  queue_exists?: boolean;
  queue_count?: number;
  queue_status_counts?: Record<string, number>;
  queue_items?: Array<Record<string, unknown>>;
  memory_path?: string;
  memory_exists?: boolean;
  memory_count?: number;
  memory_entries?: Array<Record<string, unknown>>;
}

export interface WorkflowsContract extends VersionedPayload {
  count?: number;
  items?: Array<Record<string, unknown>>;
}

export interface MCPCatalogContract extends VersionedPayload {
  catalog_root?: string;
  exists?: boolean;
  server_count?: number;
  servers?: Array<Record<string, unknown>>;
  configured_tools?: Array<Record<string, unknown>>;
}

export interface SessionsContract extends VersionedPayload {
  db_path?: string;
  exists?: boolean;
  count?: number;
  items?: Array<Record<string, unknown>>;
}

export interface ScriptlibContract extends VersionedPayload {
  root?: string;
  exists?: boolean;
  index?: Record<string, unknown>;
  catalog?: Record<string, unknown>;
}
