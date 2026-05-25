import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import { useEffect, type ReactNode } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  exportTelemetry,
  fetchAgents,
  fetchBraindrainLogs,
  fetchCommands,
  fetchConfigPage,
  fetchGit,
  fetchOverview,
  fetchPlans,
  fetchPrimer,
  fetchProcesses,
  fetchSkills,
  fetchTelemetry,
  fetchTests,
  intelligenceFallbacks,
  refreshWorkspace,
  runCommand,
  runGitAction,
  runProcessAction,
} from "@/api";
import { HomeShell } from "@/components/HomeShell";
import {
  AgentsPage,
  BraindrainLogsPage,
  ConfigPage,
  PlansPage,
  PrimerPage,
  SkillsPage,
  TestsPage,
} from "@/components/IntelligencePages";
import { BrandMark } from "@/components/ldash/BrandMark";
import { DataStream, LiveMetric, PulseActivity } from "@/components/ldash/DataStream";
import { CommandPaletteButton, KeyboardProvider, useKeyboard } from "@/components/ldash/KeyboardShortcuts";
import { ActionButton, OutputViewer, Panel, SectionHeader, StateBlock, StatusOrb, ToneChip } from "@/components/ldash/Primitives";
import { ToastProvider, useActionToasts } from "@/components/ldash/Toast";
import { PageTransition, ShimmerSkeleton } from "@/components/ldash/Transitions";
import type { CommandRunEntry, DashboardTab } from "@/data";
import { tabFromPath, tabPaths } from "@/data";
import {
  fallbackCommands,
  fallbackGit,
  fallbackOverview,
  fallbackProcesses,
  fallbackTelemetry,
} from "@/data";
import { dashboardTabs } from "@/theme";

const keyboardTabShortcuts: Array<{ key: string; tab: DashboardTab }> = [
  { key: "1", tab: "overview" },
  { key: "2", tab: "commands" },
  { key: "3", tab: "git" },
  { key: "4", tab: "processes" },
  { key: "5", tab: "telemetry" },
];

// Wrapper component to provide Toast and Keyboard contexts
export function DashboardWorkspaceWithProviders() {
  return (
    <ToastProvider>
      <KeyboardProvider>
        <DashboardWorkspace />
      </KeyboardProvider>
    </ToastProvider>
  );
}

export function DashboardWorkspace() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const location = useLocation();
  const activeTab = tabFromPath(location.pathname);
  const openTab = (tab: DashboardTab) => navigate(tabPaths[tab]);

  // Toast notification helpers
  const {
    showCommandResult,
    showGitAction,
    showProcessAction,
    showRefresh,
  } = useActionToasts();

  const overviewQuery = useQuery({
    queryKey: ["ldash", "overview"],
    queryFn: fetchOverview,
    placeholderData: fallbackOverview,
    refetchInterval: 15_000,
  });
  const commandsQuery = useQuery({
    queryKey: ["ldash", "commands"],
    queryFn: fetchCommands,
    placeholderData: fallbackCommands,
    refetchInterval: 15_000,
  });
  const gitQuery = useQuery({
    queryKey: ["ldash", "git"],
    queryFn: fetchGit,
    placeholderData: fallbackGit,
    refetchInterval: 15_000,
  });
  const processesQuery = useQuery({
    queryKey: ["ldash", "processes"],
    queryFn: fetchProcesses,
    placeholderData: fallbackProcesses,
    refetchInterval: 15_000,
  });
  const telemetryQuery = useQuery({
    queryKey: ["ldash", "telemetry"],
    queryFn: fetchTelemetry,
    placeholderData: fallbackTelemetry,
    refetchInterval: 15_000,
  });
  const logsQuery = useQuery({ queryKey: ["ldash", "braindrain-logs"], queryFn: fetchBraindrainLogs });
  const primerQuery = useQuery({ queryKey: ["ldash", "primer"], queryFn: fetchPrimer });
  const configQuery = useQuery({ queryKey: ["ldash", "config"], queryFn: fetchConfigPage });
  const agentsQuery = useQuery({ queryKey: ["ldash", "agents"], queryFn: fetchAgents });
  const skillsQuery = useQuery({ queryKey: ["ldash", "skills"], queryFn: fetchSkills });
  const plansQuery = useQuery({ queryKey: ["ldash", "plans"], queryFn: fetchPlans });
  const testsQuery = useQuery({ queryKey: ["ldash", "tests"], queryFn: fetchTests });

  const refreshOperationalQueries = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["ldash"] }),
    ]);
  };

  const refreshMutation = useMutation({
    mutationFn: refreshWorkspace,
    onSuccess: () => {
      refreshOperationalQueries();
      showRefresh("success");
    },
    onError: () => {
      showRefresh("error");
    },
  });

  const commandMutation = useMutation({
    mutationFn: (commandId: string) => runCommand(commandId),
    onSuccess: (data, commandId) => {
      refreshOperationalQueries();
      const commandName = commandsQuery.data?.groups
        ?.flatMap(g => g.items)
        ?.find(c => c.id === commandId)?.label || commandId;
      showCommandResult(
        commandName,
        data.ok ? "success" : "error",
        data.ok ? undefined : data.message
      );
    },
    onError: (error) => {
      showCommandResult("Command", "error", error instanceof Error ? error.message : "Unknown error");
    },
  });

  const gitMutation = useMutation({
    mutationFn: (action: "fetch" | "pull") => runGitAction(action),
    onSuccess: (data, action) => {
      refreshOperationalQueries();
      showGitAction(action, data.ok ? "success" : "error");
    },
    onError: () => {
      showGitAction("fetch", "error"); // Default to fetch on error
    },
  });

  const processMutation = useMutation({
    mutationFn: ({ serviceId, action }: { serviceId: string; action: "start" | "stop" | "open" }) =>
      runProcessAction(serviceId, action),
    onSuccess: (data, { serviceId, action }) => {
      refreshOperationalQueries();
      const serviceName = processesQuery.data?.items?.find(s => s.id === serviceId)?.name || serviceId;
      showProcessAction(serviceName, action, data.ok ? "success" : "error");
    },
    onError: (error, { serviceId, action }) => {
      const serviceName = processesQuery.data?.items?.find(s => s.id === serviceId)?.name || serviceId;
      showProcessAction(serviceName, action, "error");
    },
  });

  const telemetryExportMutation = useMutation({
    mutationFn: exportTelemetry,
    onSuccess: refreshOperationalQueries,
  });

  const overview = overviewQuery.data ?? fallbackOverview;
  const commands = commandsQuery.data ?? fallbackCommands;
  const git = gitQuery.data ?? fallbackGit;
  const processes = processesQuery.data ?? fallbackProcesses;
  const telemetry = telemetryQuery.data ?? fallbackTelemetry;
  const latestCommandRun = commandMutation.data?.command_run ?? commands.history[0];
  const activeTabMeta = dashboardTabs.find((tab) => tab.id === activeTab) ?? dashboardTabs[0];
  const { registerShortcut } = useKeyboard();

  useEffect(() => {
    const unsubs = keyboardTabShortcuts.map(({ key, tab }) =>
      registerShortcut({
        key,
        description: `Open ${tab} tab`,
        scope: "global",
        action: () => navigate(tabPaths[tab]),
      }),
    );
    unsubs.push(
      registerShortcut({
        key: "r",
        description: "Refresh workspace data",
        scope: "global",
        action: () => {
          if (!refreshMutation.isPending) refreshMutation.mutate();
        },
      }),
    );
    return () => unsubs.forEach((unsub) => unsub());
  }, [registerShortcut, navigate, refreshMutation.isPending, refreshMutation.mutate]);

  return (
    <div className="relative min-h-screen ld-app-shell">
      <div aria-hidden className="ambient-glow ambient-glow-top-left" />
      <div aria-hidden className="ambient-glow ambient-glow-bottom-right" />
      <div aria-hidden className="ambient-glow ambient-glow-center" />
      <div className="relative mx-auto flex min-h-screen w-full max-w-[1800px] gap-3 px-3 py-3 sm:px-4 lg:px-6">
        <aside className="hidden lg:block lg:w-20 lg:shrink-0">
          <Panel className="sticky top-3 flex min-h-[calc(100vh-1.5rem)] flex-col items-center gap-5 px-3 py-4">
            <div className="flex w-full justify-center border-b border-white/8 pb-4">
              <BrandMark size="md" showWordmark={false} compact />
            </div>
            <nav aria-label="Primary command rail" className="flex w-full flex-1 flex-col items-center gap-2">
              {dashboardTabs.map((tab) => {
                const active = activeTab === tab.id;
                return (
                  <button
                    key={tab.id}
                    type="button"
                    title={tab.label}
                    aria-label={`${tab.label} ${tab.detail}`}
                    aria-current={active ? "page" : undefined}
                    className={`flex h-12 w-12 items-center justify-center rounded-[10px] border text-xs font-semibold transition ${
                      active
                        ? "border-white/20 bg-white/14 text-white shadow-[0_0_0_1px_rgba(255,255,255,0.06)]"
                        : "border-white/8 bg-white/4 text-[color:var(--ld-text-soft)] hover:border-white/14 hover:bg-white/8 hover:text-white"
                    }`}
                    onClick={() => openTab(tab.id)}
                  >
                    <TabIcon tab={tab.id} />
                    <span className="sr-only">{tab.label}</span>
                  </button>
                );
              })}
            </nav>
            <div className="flex w-full flex-col items-center gap-2 border-t border-white/8 pt-4">
              <RailBadge label={overview.workspace.branch} short="BR" tone="violet" />
              <RailBadge label={telemetry.summary.token_saving_active ? "Saving active" : "Saving idle"} short="TK" tone="emerald" />
            </div>
          </Panel>
        </aside>

        <div className="min-w-0 flex-1">
          <div className="space-y-3 pb-3">
            <Panel className="px-4 py-4">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="min-w-0">
                  <div className="flex items-center gap-3 lg:hidden">
                    <BrandMark size="md" compact />
                    <ToneChip label={overview.workspace.branch} tone="violet" />
                  </div>
                  <p className="ld-eyebrow mt-3 lg:mt-0">LivingDash command center</p>
                  <div className="mt-2 flex flex-wrap items-center gap-3">
                    <h1 className="text-2xl font-semibold text-white">{activeTabMeta.label}</h1>
                    <ToneChip label={overview.workspace.name} tone="cyan" />
                    <ToneChip label={`${telemetry.summary.active_tools} tools`} tone="emerald" />
                    <StatusOrb
                      status={telemetry.summary.token_saving_active ? "active" : "idle"}
                      pulse={telemetry.summary.token_saving_active}
                    />
                    <CommandPaletteButton />
                    <ActionButton
                      label="Refresh workspace"
                      tone="violet"
                      busy={refreshMutation.isPending}
                      onClick={() => refreshMutation.mutate()}
                    />
                  </div>
                  <p className="ld-copy mt-3 max-w-3xl">{activeTabMeta.detail}</p>
                </div>

                <div className="grid min-w-[240px] gap-2 sm:grid-cols-3 lg:min-w-[320px]">
                  <StateBlock title="Actions" detail={String(telemetry.summary.recent_action_count)} tone="violet" />
                  <StateBlock title="Agents" detail={String(telemetry.summary.agents_online)} tone="cyan" />
                  <StateBlock title="Refresh" detail={`${telemetry.summary.refresh_age_seconds}s`} tone="amber" />
                </div>
              </div>
            </Panel>

            <Panel className="sticky top-0 z-20 bg-[color:var(--ld-surface-0)]/95 px-3 py-3 backdrop-blur-sm lg:hidden">
              <nav aria-label="Primary dashboard tabs" className="flex gap-2 overflow-x-auto pb-1 -mx-1 px-1">
                {dashboardTabs.map((tab) => {
                  const active = activeTab === tab.id;
                  return (
                    <button
                      key={tab.id}
                      type="button"
                      className={`ld-tab min-w-max min-h-[44px] touch-manipulation select-none ${active ? "ld-tab-active" : ""}`}
                      onClick={() => openTab(tab.id)}
                      aria-current={active ? "page" : undefined}
                    >
                      <span className="font-semibold">{tab.label}</span>
                      <span className="text-[11px] text-[color:var(--ld-text-soft)] line-clamp-1 max-w-[100px]">{tab.detail}</span>
                    </button>
                  );
                })}
              </nav>
            </Panel>
          </div>

          <div className="pb-4">
            <PageTransition transitionKey={activeTab}>
            {activeTab === "overview" ? (
              <HomeShell overview={overview} telemetry={telemetry} onOpenTab={openTab} />
            ) : (
              <div className="grid gap-4 xl:grid-cols-[minmax(0,1.35fr)_minmax(300px,0.72fr)]">
                <main aria-label={`${activeTabMeta.label} module`} className="min-w-0 space-y-4">
                  {activeTab === "commands" ? (
                    <CommandsModule
                      data={commands}
                      latestRun={latestCommandRun}
                      busyCommandId={commandMutation.isPending ? commandMutation.variables : null}
                      onRun={(commandId) => commandMutation.mutate(commandId)}
                    />
                  ) : null}
                  {activeTab === "git" ? (
                    <GitModule
                      data={git}
                      activeAction={gitMutation.isPending ? gitMutation.variables ?? null : null}
                      onRun={(action) => gitMutation.mutate(action)}
                    />
                  ) : null}
                  {activeTab === "processes" ? (
                    <ProcessesModule
                      data={processes}
                      pendingAction={processMutation.isPending ? processMutation.variables ?? null : null}
                      onRun={(serviceId, action) => processMutation.mutate({ serviceId, action })}
                    />
                  ) : null}
                  {activeTab === "telemetry" ? (
                    <TelemetryModule
                      data={telemetry}
                      exporting={telemetryExportMutation.isPending}
                      exportStatus={telemetryExportMutation.data?.export.created_at ?? null}
                      onExport={() => telemetryExportMutation.mutate()}
                    />
                  ) : null}
                  {activeTab === "braindrain_logs" ? (
                    <IntelligenceQueryShell query={logsQuery} fallback={intelligenceFallbacks.logs}>
                      {(data) => <BraindrainLogsPage data={data} />}
                    </IntelligenceQueryShell>
                  ) : null}
                  {activeTab === "primer" ? (
                    <IntelligenceQueryShell query={primerQuery} fallback={intelligenceFallbacks.primer}>
                      {(data) => <PrimerPage data={data} />}
                    </IntelligenceQueryShell>
                  ) : null}
                  {activeTab === "config" ? (
                    <IntelligenceQueryShell query={configQuery} fallback={intelligenceFallbacks.config}>
                      {(data) => <ConfigPage data={data} />}
                    </IntelligenceQueryShell>
                  ) : null}
                  {activeTab === "agents" ? (
                    <IntelligenceQueryShell query={agentsQuery} fallback={intelligenceFallbacks.agents}>
                      {(data) => <AgentsPage data={data} />}
                    </IntelligenceQueryShell>
                  ) : null}
                  {activeTab === "skills" ? (
                    <IntelligenceQueryShell query={skillsQuery} fallback={intelligenceFallbacks.skills}>
                      {(data) => <SkillsPage data={data} />}
                    </IntelligenceQueryShell>
                  ) : null}
                  {activeTab === "plans" ? (
                    <IntelligenceQueryShell query={plansQuery} fallback={intelligenceFallbacks.plans}>
                      {(data) => <PlansPage data={data} />}
                    </IntelligenceQueryShell>
                  ) : null}
                  {activeTab === "tests" ? (
                    <IntelligenceQueryShell query={testsQuery} fallback={intelligenceFallbacks.tests}>
                      {(data) => <TestsPage data={data} />}
                    </IntelligenceQueryShell>
                  ) : null}
                </main>

                <aside aria-label="Operational side panel" className="space-y-4">
                  <Panel className="p-5">
                    <SectionHeader
                      eyebrow="Module status"
                      title={activeTabMeta.label}
                      detail="Each module stays bounded to repo-scoped actions and a denser operator shell."
                    />
                    <div className="mt-4 grid gap-3">
                      <StateBlock title="Scope" detail={activeTabMeta.detail} tone="violet" />
                      <StateBlock title="Guardrails" detail="Only approved commands, guarded git actions, and configured services are exposed here." tone="cyan" />
                    </div>
                  </Panel>

                  <Panel className="p-5">
                    <SectionHeader eyebrow="Workspace signals" title="Current shell posture" />
                    <div className="mt-4 grid gap-2.5">
                      {overview.systems.map((item) => (
                        <MetricSignal key={item.label} label={item.label} value={item.value} detail={item.detail} tone={item.tone} />
                      ))}
                    </div>
                  </Panel>

                  {(commandMutation.data?.message || gitMutation.data?.message || processMutation.data?.message) && (
                    <Panel className="p-5">
                      <SectionHeader eyebrow="Action feedback" title="Latest mutation result" />
                      <div className="mt-4 space-y-3">
                        {commandMutation.data?.message ? (
                          <StateBlock title={commandMutation.data.message} detail={commandMutation.data.status} tone={commandMutation.data.ok ? "emerald" : "rose"} />
                        ) : null}
                        {gitMutation.data?.message ? (
                          <StateBlock title={gitMutation.data.message} detail={gitMutation.data.status} tone={gitMutation.data.ok ? "emerald" : "rose"} />
                        ) : null}
                        {processMutation.data?.message ? (
                          <StateBlock
                            title={processMutation.data.message}
                            detail={processMutation.data.status}
                            tone={processMutation.data.ok ? "emerald" : "rose"}
                          />
                        ) : null}
                      </div>
                    </Panel>
                  )}
                </aside>
              </div>
            )}
            </PageTransition>
          </div>
        </div>
      </div>
    </div>
  );
}

function TabIcon({ tab }: { tab: DashboardTab }) {
  const className = "h-[18px] w-[18px]";

  switch (tab) {
    case "overview":
      return (
        <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
          <rect x="4" y="4" width="7" height="7" rx="1.5" />
          <rect x="13" y="4" width="7" height="4" rx="1.5" />
          <rect x="13" y="10" width="7" height="10" rx="1.5" />
          <rect x="4" y="13" width="7" height="7" rx="1.5" />
        </svg>
      );
    case "commands":
      return (
        <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M6 7l4 4-4 4" />
          <path d="M12 17h6" />
        </svg>
      );
    case "git":
      return (
        <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <circle cx="7" cy="6" r="2" />
          <circle cx="17" cy="18" r="2" />
          <circle cx="17" cy="6" r="2" />
          <path d="M9 6h6" />
          <path d="M7 8v8a2 2 0 0 0 2 2h6" />
        </svg>
      );
    case "processes":
      return (
        <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <rect x="4" y="5" width="16" height="14" rx="2" />
          <path d="M8 9h8" />
          <path d="M8 13h5" />
        </svg>
      );
    case "telemetry":
      return (
        <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M5 16l4-5 3 3 5-7 2 3" />
          <path d="M5 19h14" />
        </svg>
      );
    default:
      return (
        <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
          <circle cx="12" cy="12" r="4" />
        </svg>
      );
  }
}

function IntelligenceQueryShell<T>({
  query,
  fallback,
  children,
}: {
  query: UseQueryResult<T>;
  fallback: T;
  children: (data: T) => ReactNode;
}) {
  if (query.isPending) {
    return (
      <Panel className="p-5" glow>
        <StateBlock title="Loading" detail="Fetching workspace intelligence…" tone="violet" />
        <div className="mt-4 grid gap-3">
          <ShimmerSkeleton className="h-12 w-full" />
          <ShimmerSkeleton className="h-24 w-full" />
          <ShimmerSkeleton className="h-16 w-2/3" />
        </div>
      </Panel>
    );
  }
  if (query.isError) {
    const message = query.error instanceof Error ? query.error.message : "Request failed";
    return (
      <Panel className="p-5" glow>
        <StateBlock
          title="Could not load data"
          detail={`${message}. Try Refresh workspace, re-login, or rebuild the UI (cd braindrain/ldash/ui && npm run build).`}
          tone="rose"
        />
      </Panel>
    );
  }
  return <>{children(query.data ?? fallback)}</>;
}

function RailBadge({
  label,
  short,
  tone,
}: {
  label: string;
  short: string;
  tone: "blue" | "cyan" | "emerald" | "amber" | "violet" | "rose";
}) {
  return (
    <span
      title={label}
      aria-label={label}
      className={`inline-flex h-9 w-9 min-h-[44px] min-w-[44px] items-center justify-center rounded-md text-[10px] font-semibold ${tone === "violet" ? "bg-[color:var(--ld-tone-violet-bg)] text-[color:var(--ld-tone-violet-fg)] ring-1 ring-[color:var(--ld-tone-violet-ring)]" : "bg-[color:var(--ld-tone-emerald-bg)] text-[color:var(--ld-tone-emerald-fg)] ring-1 ring-[color:var(--ld-tone-emerald-ring)]"}`}
    >
      {short}
    </span>
  );
}

function MetricSignal({
  label,
  value,
  detail,
  tone,
}: {
  label: string;
  value: string;
  detail?: string;
  tone: "blue" | "cyan" | "emerald" | "amber" | "violet" | "rose";
}) {
  return (
    <div className="ld-soft-block p-4">
      <div className="flex items-center justify-between gap-3">
        <span className="text-sm text-[color:var(--ld-text-soft)]">{label}</span>
        <ToneChip label={value} tone={tone} />
      </div>
      {detail ? <p className="ld-copy mt-3">{detail}</p> : null}
    </div>
  );
}

function CommandsModule({
  data,
  latestRun,
  busyCommandId,
  onRun,
}: {
  data: typeof fallbackCommands;
  latestRun?: CommandRunEntry;
  busyCommandId: string | null;
  onRun: (commandId: string) => void;
}) {
  return (
    <Panel className="p-5" glow>
      <SectionHeader
        eyebrow="Command Centre"
        title="Approved command presets"
        detail="This module intentionally excludes freeform shell access. Every command is config-backed and repo-scoped."
      />
      <div className="mt-6 grid gap-4 xl:grid-cols-[0.95fr_1.05fr]">
        <div className="space-y-4">
          {data.groups.map((group) => (
            <div key={group.id} className="ld-surface p-4">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <p className="ld-eyebrow">{group.label}</p>
                  <h3 className="mt-2 text-lg font-semibold text-white">{group.items.length} commands</h3>
                </div>
                <ToneChip label={group.id} tone="violet" />
              </div>
              <div className="mt-4 grid gap-3">
                {group.items.map((item) => (
                  <ActionButton
                    key={item.id}
                    label={item.label}
                    detail={`${item.description} · ${item.cwd}`}
                    tone="violet"
                    busy={busyCommandId === item.id}
                    onClick={() => onRun(item.id)}
                  />
                ))}
              </div>
            </div>
          ))}
        </div>

        <div className="space-y-4">
          <div className="ld-surface p-4">
            <SectionHeader
              eyebrow="Output"
              title={latestRun ? latestRun.label : "No command selected"}
              detail={latestRun ? `${latestRun.status} · exit ${latestRun.returncode} · ${latestRun.duration_ms}ms` : "Run a preset to capture stdout and stderr."}
            />
            <div className="mt-4">
              <OutputViewer stdout={latestRun?.stdout} stderr={latestRun?.stderr} />
            </div>
          </div>

          <div className="ld-surface p-4">
            <SectionHeader eyebrow="History" title="Recent command runs" />
            <div className="mt-4 grid gap-3">
              {data.history.length ? (
                data.history.map((entry) => (
                  <div key={`${entry.id}-${entry.finished_at}`} className="ld-soft-block p-4">
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-sm font-medium text-white">{entry.label}</span>
                      <ToneChip label={entry.status} tone={entry.ok ? "emerald" : "rose"} />
                    </div>
                    <p className="ld-copy mt-3">{entry.finished_at}</p>
                  </div>
                ))
              ) : (
                <StateBlock title="No runs yet" detail="The command history will appear here after the first approved run." />
              )}
            </div>
          </div>
        </div>
      </div>
    </Panel>
  );
}

function GitModule({
  data,
  activeAction,
  onRun,
}: {
  data: typeof fallbackGit;
  activeAction: "fetch" | "pull" | null;
  onRun: (action: "fetch" | "pull") => void;
}) {
  const summary = data.summary;
  return (
    <Panel className="p-5" glow>
      <SectionHeader
        eyebrow="Git Status"
        title={`Branch ${summary.branch}`}
        detail="Only guarded sync operations are exposed in the MVP. Push and destructive repo operations remain out of scope."
        action={<ToneChip label={summary.dirty ? "dirty" : "clean"} tone={summary.dirty ? "amber" : "emerald"} />}
      />
      <div className="mt-6 grid gap-4 xl:grid-cols-[0.9fr_1.1fr]">
        <div className="ld-surface p-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <StateBlock title="Ahead" detail={String(summary.ahead)} tone="violet" />
            <StateBlock title="Behind" detail={String(summary.behind)} tone="cyan" />
            <StateBlock title="Staged" detail={String(summary.staged)} tone="emerald" />
            <StateBlock title="Unstaged" detail={String(summary.unstaged)} tone="amber" />
            <StateBlock title="Untracked" detail={String(summary.untracked)} tone="rose" />
          </div>
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            {data.actions.map((action) => (
              <ActionButton
                key={action.id}
                label={action.label}
                detail={action.description}
                tone={action.id === "fetch" ? "cyan" : "violet"}
                busy={activeAction === action.id}
                onClick={() => onRun(action.id as "fetch" | "pull")}
              />
            ))}
          </div>
        </div>

        <div className="ld-surface p-4">
          <SectionHeader eyebrow="Recent commits" title="Latest repo activity" />
          <div className="mt-4 grid gap-3">
            {summary.recent_commits.map((commit) => (
              <div key={`${commit.hash}-${commit.subject}`} className="ld-soft-block p-4">
                <div className="flex items-center justify-between gap-3">
                  <span className="text-sm font-medium text-white">{commit.subject}</span>
                  <ToneChip label={commit.hash} tone="violet" />
                </div>
                <p className="ld-copy mt-3">{commit.age}</p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </Panel>
  );
}

function ProcessesModule({
  data,
  pendingAction,
  onRun,
}: {
  data: typeof fallbackProcesses;
  pendingAction: { serviceId: string; action: "start" | "stop" | "open" } | null;
  onRun: (serviceId: string, action: "start" | "stop" | "open") => void;
}) {
  return (
    <Panel className="p-5" glow>
      <SectionHeader
        eyebrow="Process Monitor"
        title="Repo-scoped services only"
        detail="The dashboard tracks configured workspace services, not arbitrary local processes."
      />
      <div className="mt-6 grid gap-4">
        {data.items.map((service) => (
          <div key={service.id} className="ld-surface p-4">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <p className="ld-eyebrow">{service.cwd}</p>
                <h3 className="mt-2 text-xl font-semibold text-white">{service.name}</h3>
                <p className="ld-copy mt-3 max-w-2xl">{service.description}</p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <StatusOrb
                  status={service.status === "running" ? "active" : service.healthy ? "idle" : "warning"}
                  pulse={service.status === "running"}
                />
                <ToneChip label={service.status} tone={service.status === "running" ? "emerald" : "amber"} />
                <ToneChip label={service.healthy ? "healthy" : "idle"} tone={service.healthy ? "cyan" : "violet"} />
              </div>
            </div>

            <div className="mt-4 grid gap-3 md:grid-cols-3">
              {(["start", "stop", "open"] as const).map((action) => (
                <ActionButton
                  key={action}
                  label={action[0].toUpperCase() + action.slice(1)}
                  detail={action === "open" ? service.open_target ?? "No target configured" : `${service.name} ${action}`}
                  tone={action === "stop" ? "rose" : action === "open" ? "cyan" : "emerald"}
                  busy={pendingAction?.serviceId === service.id && pendingAction?.action === action}
                  disabled={!service.allowed_actions.includes(action)}
                  onClick={() => onRun(service.id, action)}
                />
              ))}
            </div>
          </div>
        ))}
      </div>
    </Panel>
  );
}

function TelemetryModule({
  data,
  exporting,
  exportStatus,
  onExport,
}: {
  data: typeof fallbackTelemetry;
  exporting: boolean;
  exportStatus: string | null;
  onExport: () => void;
}) {
  const orbStatus = data.summary.token_saving_active ? "active" : data.summary.env_drift > 0 ? "warning" : "idle";

  return (
    <Panel className="p-5" glow>
      <SectionHeader
        eyebrow="Telemetry"
        title="Runtime signals"
        detail="Token-saving, active tools, refresh age, and recent action events are summarized here."
        action={
          <div className="flex flex-wrap items-center gap-2">
            <PulseActivity label={data.summary.token_saving_active ? "Saving" : "Idle"} />
            <StatusOrb status={orbStatus} pulse={data.summary.token_saving_active} />
            <ActionButton label="Export snapshot" tone="violet" busy={exporting} onClick={onExport} />
          </div>
        }
      />

      <div className="mt-5 ld-surface p-4">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <LiveMetric value={data.summary.active_tools} unit=" active tools" />
          <DataStream barCount={32} maxHeight={96} className="min-h-[96px] flex-1 max-w-md" />
        </div>
      </div>

      <div className="mt-6 grid gap-4 xl:grid-cols-[0.9fr_1.1fr]">
        <div className="ld-surface p-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <StateBlock title="Active tools" detail={String(data.summary.active_tools)} tone="emerald" />
            <StateBlock title="Agents online" detail={String(data.summary.agents_online)} tone="cyan" />
            <StateBlock title="Refresh age" detail={`${data.summary.refresh_age_seconds}s`} tone="amber" />
            <StateBlock title="Recent actions" detail={String(data.summary.recent_action_count)} tone="violet" />
          </div>
          {exportStatus ? <p className="ld-copy mt-4">Last export written at {exportStatus}.</p> : null}
        </div>

        <div className="ld-surface p-4">
          <SectionHeader eyebrow="Recent events" title="Latest command telemetry" />
          <div className="mt-4 grid gap-3">
            {data.events.length ? (
              data.events.map((event) => (
                <div key={`${event.label}-${event.time}`} className="ld-soft-block p-4">
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-sm font-medium text-white">{event.label}</span>
                    <ToneChip label={event.status} tone={event.status === "success" ? "emerald" : "amber"} />
                  </div>
                  <p className="ld-copy mt-3">{event.detail}</p>
                </div>
              ))
            ) : (
              <StateBlock title="No telemetry yet" detail="Events will appear here after the first module action completes." />
            )}
          </div>
        </div>
      </div>
    </Panel>
  );
}
