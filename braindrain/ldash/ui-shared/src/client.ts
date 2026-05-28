import type {
  ActionEnvelope,
  AgentsContract,
  AuthSession,
  BraindrainLogsContract,
  CommandsContract,
  ConfigPageContract,
  GitContract,
  GitopsContract,
  LoginPayload,
  MCPCatalogContract,
  OverviewContract,
  PlansContract,
  PrimerContract,
  ProcessesContract,
  ScriptlibContract,
  SessionsContract,
  SkillsContract,
  TelemetryContract,
  TestsContract,
  WorkflowsContract,
} from "./contract";

export interface LivingDashClientOptions {
  baseUrl?: string;
  useDevFallback?: boolean;
}

export class LivingDashClient {
  private readonly baseUrl: string;
  private readonly useDevFallback: boolean;

  constructor(options: LivingDashClientOptions = {}) {
    this.baseUrl = (options.baseUrl ?? "").replace(/\/$/, "");
    this.useDevFallback = options.useDevFallback ?? false;
  }

  private endpoint(path: string): string {
    return `${this.baseUrl}${path}`;
  }

  private async readJSON<T>(response: Response): Promise<T> {
    const text = await response.text();
    if (!response.ok) {
      throw new Error(text || `Request failed with status ${response.status}`);
    }
    if (!text) {
      return {} as T;
    }
    return JSON.parse(text) as T;
  }

  private async requestJSON<T>(path: string, init?: RequestInit): Promise<T> {
    const headers = new Headers(init?.headers);
    if (!headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    const response = await fetch(this.endpoint(path), {
      credentials: "include",
      headers,
      ...init,
    });
    return this.readJSON<T>(response);
  }

  private async withFallback<T>(request: () => Promise<T>, fallback: T): Promise<T> {
    try {
      return await request();
    } catch (error) {
      if (!this.useDevFallback) {
        throw error;
      }
      return fallback;
    }
  }

  fetchOverview(fallback?: OverviewContract): Promise<OverviewContract> {
    if (fallback) {
      return this.withFallback(() => this.requestJSON<OverviewContract>("/api/overview"), fallback);
    }
    return this.requestJSON<OverviewContract>("/api/overview");
  }

  fetchCommands(fallback?: CommandsContract): Promise<CommandsContract> {
    if (fallback) {
      return this.withFallback(() => this.requestJSON<CommandsContract>("/api/commands"), fallback);
    }
    return this.requestJSON<CommandsContract>("/api/commands");
  }

  fetchGit(fallback?: GitContract): Promise<GitContract> {
    if (fallback) {
      return this.withFallback(() => this.requestJSON<GitContract>("/api/git"), fallback);
    }
    return this.requestJSON<GitContract>("/api/git");
  }

  fetchProcesses(fallback?: ProcessesContract): Promise<ProcessesContract> {
    if (fallback) {
      return this.withFallback(() => this.requestJSON<ProcessesContract>("/api/processes"), fallback);
    }
    return this.requestJSON<ProcessesContract>("/api/processes");
  }

  fetchTelemetry(fallback?: TelemetryContract): Promise<TelemetryContract> {
    if (fallback) {
      return this.withFallback(() => this.requestJSON<TelemetryContract>("/api/telemetry"), fallback);
    }
    return this.requestJSON<TelemetryContract>("/api/telemetry");
  }

  fetchAuthSession(): Promise<AuthSession> {
    return this.requestJSON<AuthSession>("/api/auth/session");
  }

  login(payload: LoginPayload): Promise<AuthSession> {
    return this.requestJSON<AuthSession>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  refreshWorkspace(): Promise<{ ok: boolean; schema_version?: string }> {
    return this.requestJSON("/api/workspace/refresh", { method: "POST" });
  }

  runCommand(commandId: string): Promise<ActionEnvelope<Record<string, unknown>>> {
    return this.requestJSON(`/api/commands/run/${commandId}`, { method: "POST" });
  }

  runGitAction(action: "fetch" | "pull"): Promise<ActionEnvelope<Record<string, unknown>>> {
    return this.requestJSON(`/api/git/${action}`, { method: "POST" });
  }

  runProcessAction(serviceId: string, action: "start" | "stop" | "open"): Promise<ActionEnvelope<Record<string, unknown>>> {
    return this.requestJSON(`/api/processes/${serviceId}/${action}`, { method: "POST" });
  }

  fetchAgents(): Promise<AgentsContract> {
    return this.requestJSON<AgentsContract>("/api/agents");
  }

  fetchSkills(): Promise<SkillsContract> {
    return this.requestJSON<SkillsContract>("/api/skills");
  }

  fetchPlans(): Promise<PlansContract> {
    return this.requestJSON<PlansContract>("/api/plans");
  }

  fetchTests(): Promise<TestsContract> {
    return this.requestJSON<TestsContract>("/api/tests");
  }

  fetchPrimer(): Promise<PrimerContract> {
    return this.requestJSON<PrimerContract>("/api/primer");
  }

  fetchConfig(): Promise<ConfigPageContract> {
    return this.requestJSON<ConfigPageContract>("/api/config");
  }

  fetchBraindrainLogs(): Promise<BraindrainLogsContract> {
    return this.requestJSON<BraindrainLogsContract>("/api/braindrain/logs?limit=100");
  }

  fetchGitops(): Promise<GitopsContract> {
    return this.requestJSON<GitopsContract>("/api/gitops");
  }

  fetchWorkflows(): Promise<WorkflowsContract> {
    return this.requestJSON<WorkflowsContract>("/api/workflows");
  }

  fetchMCPCatalog(): Promise<MCPCatalogContract> {
    return this.requestJSON<MCPCatalogContract>("/api/mcp-catalog");
  }

  fetchSessions(limit = 40): Promise<SessionsContract> {
    return this.requestJSON<SessionsContract>(`/api/sessions?limit=${Math.max(1, limit)}`);
  }

  fetchScriptlib(): Promise<ScriptlibContract> {
    return this.requestJSON<ScriptlibContract>("/api/scriptlib");
  }
}

export const defaultClient = new LivingDashClient({
  useDevFallback: typeof import.meta !== "undefined" && Boolean(import.meta.env?.DEV),
});
