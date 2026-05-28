import { useQuery, type UseQueryOptions } from "@tanstack/react-query";

import type {
  AgentsContract,
  BraindrainLogsContract,
  CommandsContract,
  ConfigPageContract,
  GitContract,
  GitopsContract,
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
import { defaultClient } from "./client";

type QueryOpts<T> = Omit<UseQueryOptions<T, Error, T, readonly unknown[]>, "queryKey" | "queryFn">;

export const livingdashQueryKeys = {
  overview: ["livingdash", "overview"] as const,
  commands: ["livingdash", "commands"] as const,
  git: ["livingdash", "git"] as const,
  processes: ["livingdash", "processes"] as const,
  telemetry: ["livingdash", "telemetry"] as const,
  agents: ["livingdash", "agents"] as const,
  skills: ["livingdash", "skills"] as const,
  plans: ["livingdash", "plans"] as const,
  tests: ["livingdash", "tests"] as const,
  primer: ["livingdash", "primer"] as const,
  config: ["livingdash", "config"] as const,
  logs: ["livingdash", "logs"] as const,
  gitops: ["livingdash", "gitops"] as const,
  workflows: ["livingdash", "workflows"] as const,
  mcpCatalog: ["livingdash", "mcp-catalog"] as const,
  sessions: (limit: number) => ["livingdash", "sessions", limit] as const,
  scriptlib: ["livingdash", "scriptlib"] as const,
};

export function useOverviewQuery(options?: QueryOpts<OverviewContract>) {
  return useQuery({
    queryKey: livingdashQueryKeys.overview,
    queryFn: () => defaultClient.fetchOverview(),
    ...options,
  });
}

export function useCommandsQuery(options?: QueryOpts<CommandsContract>) {
  return useQuery({
    queryKey: livingdashQueryKeys.commands,
    queryFn: () => defaultClient.fetchCommands(),
    ...options,
  });
}

export function useGitQuery(options?: QueryOpts<GitContract>) {
  return useQuery({
    queryKey: livingdashQueryKeys.git,
    queryFn: () => defaultClient.fetchGit(),
    ...options,
  });
}

export function useProcessesQuery(options?: QueryOpts<ProcessesContract>) {
  return useQuery({
    queryKey: livingdashQueryKeys.processes,
    queryFn: () => defaultClient.fetchProcesses(),
    ...options,
  });
}

export function useTelemetryQuery(options?: QueryOpts<TelemetryContract>) {
  return useQuery({
    queryKey: livingdashQueryKeys.telemetry,
    queryFn: () => defaultClient.fetchTelemetry(),
    ...options,
  });
}

export function useAgentsQuery(options?: QueryOpts<AgentsContract>) {
  return useQuery({
    queryKey: livingdashQueryKeys.agents,
    queryFn: () => defaultClient.fetchAgents(),
    ...options,
  });
}

export function useSkillsQuery(options?: QueryOpts<SkillsContract>) {
  return useQuery({
    queryKey: livingdashQueryKeys.skills,
    queryFn: () => defaultClient.fetchSkills(),
    ...options,
  });
}

export function usePlansQuery(options?: QueryOpts<PlansContract>) {
  return useQuery({
    queryKey: livingdashQueryKeys.plans,
    queryFn: () => defaultClient.fetchPlans(),
    ...options,
  });
}

export function useTestsQuery(options?: QueryOpts<TestsContract>) {
  return useQuery({
    queryKey: livingdashQueryKeys.tests,
    queryFn: () => defaultClient.fetchTests(),
    ...options,
  });
}

export function usePrimerQuery(options?: QueryOpts<PrimerContract>) {
  return useQuery({
    queryKey: livingdashQueryKeys.primer,
    queryFn: () => defaultClient.fetchPrimer(),
    ...options,
  });
}

export function useConfigQuery(options?: QueryOpts<ConfigPageContract>) {
  return useQuery({
    queryKey: livingdashQueryKeys.config,
    queryFn: () => defaultClient.fetchConfig(),
    ...options,
  });
}

export function useLogsQuery(options?: QueryOpts<BraindrainLogsContract>) {
  return useQuery({
    queryKey: livingdashQueryKeys.logs,
    queryFn: () => defaultClient.fetchBraindrainLogs(),
    ...options,
  });
}

export function useGitopsQuery(options?: QueryOpts<GitopsContract>) {
  return useQuery({
    queryKey: livingdashQueryKeys.gitops,
    queryFn: () => defaultClient.fetchGitops(),
    ...options,
  });
}

export function useWorkflowsQuery(options?: QueryOpts<WorkflowsContract>) {
  return useQuery({
    queryKey: livingdashQueryKeys.workflows,
    queryFn: () => defaultClient.fetchWorkflows(),
    ...options,
  });
}

export function useMCPCatalogQuery(options?: QueryOpts<MCPCatalogContract>) {
  return useQuery({
    queryKey: livingdashQueryKeys.mcpCatalog,
    queryFn: () => defaultClient.fetchMCPCatalog(),
    ...options,
  });
}

export function useSessionsQuery(limit = 40, options?: QueryOpts<SessionsContract>) {
  return useQuery({
    queryKey: livingdashQueryKeys.sessions(limit),
    queryFn: () => defaultClient.fetchSessions(limit),
    ...options,
  });
}

export function useScriptlibQuery(options?: QueryOpts<ScriptlibContract>) {
  return useQuery({
    queryKey: livingdashQueryKeys.scriptlib,
    queryFn: () => defaultClient.fetchScriptlib(),
    ...options,
  });
}
