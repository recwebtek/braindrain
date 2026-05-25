import type {
  ActionEnvelope,
  AgentsContract,
  BraindrainLogsContract,
  CommandRunEntry,
  CommandsContract,
  ConfigPageContract,
  GitContract,
  OverviewContract,
  PlansContract,
  PrimerContract,
  ProcessesContract,
  ServiceEntry,
  SkillsContract,
  TelemetryContract,
  TestsContract,
} from "@/data";
import {
  fallbackCommands,
  fallbackGit,
  fallbackOverview,
  fallbackProcesses,
  fallbackTelemetry,
} from "@/data";

export interface AuthSession {
  authenticated: boolean;
  userName?: string;
  email?: string;
  expiresAt?: string;
}

export interface LoginPayload {
  username: string;
  password: string;
}

async function readJSON<T>(response: Response): Promise<T> {
  const text = await response.text();
  if (!response.ok) {
    throw new Error(text || `Request failed with status ${response.status}`);
  }
  if (!text) {
    return {} as T;
  }
  return JSON.parse(text) as T;
}

async function requestJSON<T>(input: RequestInfo | URL, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  headers.set("Content-Type", "application/json");
  const response = await fetch(input, {
    credentials: "include",
    headers,
    ...init,
  });
  return readJSON<T>(response);
}

const DEV_FALLBACK = import.meta.env.DEV;

async function withFallback<T>(request: () => Promise<T>, fallback: T): Promise<T> {
  try {
    return await request();
  } catch (error) {
    if (!DEV_FALLBACK) {
      throw error;
    }
    return fallback;
  }
}

export async function fetchOverview(): Promise<OverviewContract> {
  return withFallback(() => requestJSON<OverviewContract>("/api/overview"), fallbackOverview);
}

export async function fetchCommands(): Promise<CommandsContract> {
  return withFallback(() => requestJSON<CommandsContract>("/api/commands"), fallbackCommands);
}

export async function fetchGit(): Promise<GitContract> {
  return withFallback(() => requestJSON<GitContract>("/api/git"), fallbackGit);
}

export async function fetchProcesses(): Promise<ProcessesContract> {
  return withFallback(() => requestJSON<ProcessesContract>("/api/processes"), fallbackProcesses);
}

export async function fetchTelemetry(): Promise<TelemetryContract> {
  return withFallback(() => requestJSON<TelemetryContract>("/api/telemetry"), fallbackTelemetry);
}

export async function runCommand(commandId: string): Promise<ActionEnvelope<CommandRunEntry>> {
  return requestJSON<ActionEnvelope<CommandRunEntry>>(`/api/commands/run/${commandId}`, {
    method: "POST",
  });
}

export async function runGitAction(action: "fetch" | "pull"): Promise<ActionEnvelope<Record<string, unknown>>> {
  return requestJSON<ActionEnvelope<Record<string, unknown>>>(`/api/git/${action}`, {
    method: "POST",
  });
}

export async function runProcessAction(
  serviceId: string,
  action: "start" | "stop" | "open",
): Promise<ActionEnvelope<ServiceEntry>> {
  return requestJSON<ActionEnvelope<ServiceEntry>>(`/api/processes/${serviceId}/${action}`, {
    method: "POST",
  });
}

export async function exportTelemetry(): Promise<{ version: string; export: { created_at: string; telemetry: TelemetryContract } }> {
  return requestJSON("/api/telemetry/export");
}

export async function fetchAuthSession(): Promise<AuthSession> {
  return requestJSON<AuthSession>("/api/auth/session");
}

export async function login(payload: LoginPayload): Promise<AuthSession> {
  return requestJSON<AuthSession>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function refreshWorkspace(): Promise<{ ok: boolean }> {
  return requestJSON("/api/workspace/refresh", { method: "POST" });
}

export async function fetchBraindrainLogs(): Promise<BraindrainLogsContract> {
  return requestJSON<BraindrainLogsContract>("/api/braindrain/logs?limit=100");
}

export async function fetchPrimer(): Promise<PrimerContract> {
  return requestJSON<PrimerContract>("/api/primer");
}

export async function fetchConfigPage(): Promise<ConfigPageContract> {
  return requestJSON<ConfigPageContract>("/api/config");
}

export async function fetchAgents(): Promise<AgentsContract> {
  return requestJSON<AgentsContract>("/api/agents");
}

export async function fetchSkills(): Promise<SkillsContract> {
  return requestJSON<SkillsContract>("/api/skills");
}

export async function fetchPlans(): Promise<PlansContract> {
  return requestJSON<PlansContract>("/api/plans");
}

export async function fetchTests(): Promise<TestsContract> {
  return requestJSON<TestsContract>("/api/tests");
}

const emptyAgents: AgentsContract = { version: "2.0", count: 0, template_count: 0, items: [], updated_at: "" };
const emptySkills: SkillsContract = {
  version: "2.0",
  installed_count: 0,
  template_count: 0,
  drift_missing: [],
  installed: [],
  templates: [],
  updated_at: "",
};
const emptyPrimer: PrimerContract = { version: "2.0", primer: {}, updated_at: "" };
const emptyConfig: ConfigPageContract = { version: "2.0", read_only: true, hub_config: {}, memory: {}, updated_at: "" };
const emptyLogs: BraindrainLogsContract = { version: "2.0" };
const emptyPlans: PlansContract = { version: "2.0", updated_at: "" };
const emptyTests: TestsContract = {
  version: "2.0",
  python_tests: [],
  python_test_count: 0,
  scripts: [],
  ci_workflows: [],
  updated_at: "",
};

export const intelligenceFallbacks = {
  agents: emptyAgents,
  skills: emptySkills,
  primer: emptyPrimer,
  config: emptyConfig,
  logs: emptyLogs,
  plans: emptyPlans,
  tests: emptyTests,
};
