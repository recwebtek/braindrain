import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  defaultClient,
  livingdashQueryKeys,
  type CommandsContract,
  useCommandsQuery,
  useGitQuery,
  useGitopsQuery,
  useLogsQuery,
  useProcessesQuery,
  useScriptlibQuery,
  useSessionsQuery,
  useTelemetryQuery,
  useWorkflowsQuery,
} from "@livingdash/ui-shared";

type DeckItem = {
  id: string;
  label: string;
  description: string;
  scope: "command" | "git";
  commandId?: string;
  gitAction?: "fetch" | "pull";
};

const authSessionKey = ["livingdash", "auth-session"] as const;

function AuthGate({ children }: { children: JSX.Element }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const queryClient = useQueryClient();

  const sessionQuery = useQuery({
    queryKey: authSessionKey,
    queryFn: () => defaultClient.fetchAuthSession(),
    retry: false,
  });

  const loginMutation = useMutation({
    mutationFn: () =>
      defaultClient.login({
        username,
        password,
      }),
    onSuccess: async () => {
      setError("");
      await queryClient.invalidateQueries({ queryKey: authSessionKey });
    },
    onError: (loginError) => {
      setError(loginError instanceof Error ? loginError.message : "Login failed");
    },
  });

  if (sessionQuery.isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-slate-300">
        checking session...
      </div>
    );
  }

  const session = sessionQuery.data;
  if (session?.authenticated) {
    return children;
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-md rounded-xl border border-violet-400/25 bg-black/40 p-6 shadow-glow backdrop-blur">
        <h1 className="text-xl font-semibold text-cyan-300">LivingDash PILOT</h1>
        <p className="mt-2 text-sm text-slate-300">Sign in to start command-deck mode.</p>
        <form
          className="mt-6 space-y-3"
          onSubmit={(event) => {
            event.preventDefault();
            loginMutation.mutate();
          }}
        >
          <label className="block">
            <span className="mb-1 block text-xs uppercase tracking-wide text-slate-400">username</span>
            <input
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none ring-cyan-400/70 focus:ring"
              autoComplete="username"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs uppercase tracking-wide text-slate-400">password</span>
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none ring-cyan-400/70 focus:ring"
              autoComplete="current-password"
            />
          </label>
          {error ? <p className="text-xs text-rose-300">{error}</p> : null}
          <button
            type="submit"
            disabled={loginMutation.isPending}
            className="w-full rounded-md border border-cyan-500/50 bg-cyan-500/10 px-3 py-2 text-sm font-medium text-cyan-100 transition hover:bg-cyan-500/20 disabled:opacity-60"
          >
            {loginMutation.isPending ? "signing in..." : "login"}
          </button>
        </form>
      </div>
    </div>
  );
}

function DeckPanel({
  open,
  setOpen,
  items,
}: {
  open: boolean;
  setOpen: (open: boolean) => void;
  items: DeckItem[];
}) {
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const queryClient = useQueryClient();

  const runMutation = useMutation({
    mutationFn: async (item: DeckItem) => {
      if (item.scope === "command" && item.commandId) {
        return defaultClient.runCommand(item.commandId);
      }
      if (item.scope === "git" && item.gitAction) {
        return defaultClient.runGitAction(item.gitAction);
      }
      throw new Error("Unsupported action");
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: livingdashQueryKeys.commands }),
        queryClient.invalidateQueries({ queryKey: livingdashQueryKeys.git }),
        queryClient.invalidateQueries({ queryKey: livingdashQueryKeys.telemetry }),
        queryClient.invalidateQueries({ queryKey: livingdashQueryKeys.logs }),
      ]);
    },
  });

  const filtered = useMemo(() => {
    const normalized = query.toLowerCase().trim();
    if (!normalized) {
      return items;
    }
    return items.filter((item) =>
      `${item.label} ${item.description}`.toLowerCase().includes(normalized),
    );
  }, [items, query]);

  useEffect(() => {
    setActive(0);
  }, [query]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const isOpenCmd = (event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k";
      if (isOpenCmd) {
        event.preventDefault();
        setOpen(!open);
        return;
      }
      if (!open) {
        return;
      }
      if (event.key === "Escape") {
        event.preventDefault();
        setOpen(false);
      } else if (event.key === "ArrowDown") {
        event.preventDefault();
        setActive((prev) => Math.min(prev + 1, Math.max(filtered.length - 1, 0)));
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        setActive((prev) => Math.max(prev - 1, 0));
      } else if (event.key === "Enter" && filtered[active]) {
        event.preventDefault();
        runMutation.mutate(filtered[active]);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [active, filtered, open, runMutation, setOpen]);

  if (!open) {
    return null;
  }

  return (
    <div className="fixed inset-0 z-30 bg-black/50 px-4 py-14 backdrop-blur-sm">
      <div className="mx-auto max-w-3xl overflow-hidden rounded-xl border border-cyan-400/35 bg-slate-950/95 shadow-glow">
        <div className="border-b border-slate-800 px-4 py-3">
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            autoFocus
            placeholder="type a command..."
            className="w-full bg-transparent text-sm text-cyan-100 outline-none placeholder:text-slate-500"
          />
        </div>
        <div className="max-h-[60vh] overflow-auto px-2 py-2">
          {!filtered.length ? (
            <div className="rounded-md border border-dashed border-slate-800 p-4 text-sm text-slate-400">
              no command matches your query
            </div>
          ) : (
            filtered.map((item, index) => (
              <button
                key={item.id}
                type="button"
                onClick={() => runMutation.mutate(item)}
                className={`mb-1 block w-full rounded-md border px-3 py-2 text-left text-sm ${
                  index === active
                    ? "border-cyan-400/50 bg-cyan-400/10 text-cyan-100"
                    : "border-slate-800 bg-slate-900/40 text-slate-200 hover:border-slate-700"
                }`}
              >
                <div className="flex items-center justify-between gap-4">
                  <span>{item.label}</span>
                  <span className="text-xs uppercase tracking-wide text-slate-500">{item.scope}</span>
                </div>
                <p className="mt-1 text-xs text-slate-400">{item.description}</p>
              </button>
            ))
          )}
        </div>
      </div>
    </div>
  );
}

function DataPanel({
  title,
  loading,
  children,
  emptyText = "no data available",
}: {
  title: string;
  loading: boolean;
  children?: JSX.Element;
  emptyText?: string;
}) {
  return (
    <section className="rounded-lg border border-slate-800 bg-black/30 p-4">
      <h2 className="text-xs uppercase tracking-[0.15em] text-slate-400">{title}</h2>
      <div className="mt-3">
        {loading ? (
          <p className="text-sm text-slate-500">loading...</p>
        ) : children ? (
          children
        ) : (
          <p className="text-sm text-slate-500">{emptyText}</p>
        )}
      </div>
    </section>
  );
}

function buildDeckItems(commands?: CommandsContract): DeckItem[] {
  const dynamic =
    commands?.groups.flatMap((group) =>
      group.items.map((item) => ({
        id: `${group.id}:${item.id}`,
        label: item.label,
        description: item.description,
        scope: "command" as const,
        commandId: item.id,
      })),
    ) ?? [];

  return [
    ...dynamic,
    { id: "git-fetch", label: "git fetch", description: "Fetch origin updates", scope: "git", gitAction: "fetch" },
    { id: "git-pull", label: "git pull", description: "Pull latest changes", scope: "git", gitAction: "pull" },
  ];
}

function PilotDeck() {
  const [deckOpen, setDeckOpen] = useState(false);

  const commandsQuery = useCommandsQuery();
  const gitQuery = useGitQuery();
  const processesQuery = useProcessesQuery();
  const telemetryQuery = useTelemetryQuery();
  const logsQuery = useLogsQuery();
  const sessionsQuery = useSessionsQuery(20);
  const gitopsQuery = useGitopsQuery();
  const workflowsQuery = useWorkflowsQuery();
  const scriptlibQuery = useScriptlibQuery();

  const deckItems = useMemo(() => buildDeckItems(commandsQuery.data), [commandsQuery.data]);

  return (
    <div className="relative min-h-screen px-4 py-4 md:px-7 md:py-6">
      <DeckPanel open={deckOpen} setOpen={setDeckOpen} items={deckItems} />

      <header className="mb-5 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-cyan-500/25 bg-black/35 px-4 py-3">
        <div>
          <h1 className="text-lg font-semibold text-cyan-300">LivingDash PILOT</h1>
          <p className="text-xs text-slate-400">keyboard-first command deck for sidecar operations</p>
        </div>
        <button
          type="button"
          onClick={() => setDeckOpen(true)}
          className="rounded-md border border-cyan-500/50 bg-cyan-500/10 px-3 py-2 text-sm text-cyan-100 hover:bg-cyan-500/20"
        >
          open deck <span className="text-xs text-cyan-300/80">(⌘/Ctrl+K)</span>
        </button>
      </header>

      <main className="grid grid-cols-1 gap-3 lg:grid-cols-3">
        <DataPanel title="Commands" loading={commandsQuery.isLoading}>
          {deckItems.length ? (
            <ul className="space-y-2 text-xs">
              {deckItems.slice(0, 7).map((item) => (
                <li key={item.id} className="rounded border border-slate-800 bg-slate-900/30 px-2 py-1.5 text-slate-300">
                  {item.label}
                </li>
              ))}
            </ul>
          ) : undefined}
        </DataPanel>

        <DataPanel title="Git" loading={gitQuery.isLoading}>
          {gitQuery.data?.summary ? (
            <div className="space-y-1 text-sm text-slate-300">
              <p>branch: {gitQuery.data.summary.branch}</p>
              <p>dirty: {gitQuery.data.summary.dirty ? "yes" : "no"}</p>
              <p>
                ahead/behind: {gitQuery.data.summary.ahead}/{gitQuery.data.summary.behind}
              </p>
            </div>
          ) : undefined}
        </DataPanel>

        <DataPanel title="Processes" loading={processesQuery.isLoading}>
          {processesQuery.data?.items.length ? (
            <ul className="space-y-1 text-xs">
              {processesQuery.data.items
                .slice(0, 5)
                .map((service: { id: string; name: string; healthy: boolean; status: string }) => (
                <li key={service.id} className="text-slate-300">
                  {service.name}:{" "}
                  <span className={service.healthy ? "text-emerald-300" : "text-amber-300"}>{service.status}</span>
                </li>
              ))}
            </ul>
          ) : undefined}
        </DataPanel>

        <DataPanel title="Telemetry" loading={telemetryQuery.isLoading}>
          {telemetryQuery.data?.summary ? (
            <div className="space-y-1 text-xs text-slate-300">
              <p>active tools: {telemetryQuery.data.summary.active_tools}</p>
              <p>agents online: {telemetryQuery.data.summary.agents_online}</p>
              <p>refresh age: {telemetryQuery.data.summary.refresh_age_seconds}s</p>
            </div>
          ) : undefined}
        </DataPanel>

        <DataPanel title="Logs" loading={logsQuery.isLoading}>
          {logsQuery.data ? (
            <div className="space-y-1 text-xs text-slate-300">
              <p>observer logs: {logsQuery.data.observer ? "present" : "none"}</p>
              <p>session logs: {logsQuery.data.session_jsonl ? "present" : "none"}</p>
              <p>token checkpoints: {logsQuery.data.token_checkpoints?.length ?? 0}</p>
            </div>
          ) : undefined}
        </DataPanel>

        <DataPanel title="Sessions" loading={sessionsQuery.isLoading}>
          {sessionsQuery.data ? (
            <div className="space-y-1 text-xs text-slate-300">
              <p>db exists: {sessionsQuery.data.exists ? "yes" : "no"}</p>
              <p>count: {sessionsQuery.data.count ?? 0}</p>
            </div>
          ) : undefined}
        </DataPanel>

        <DataPanel title="Gitops" loading={gitopsQuery.isLoading}>
          {gitopsQuery.data ? (
            <div className="space-y-1 text-xs text-slate-300">
              <p>queue items: {gitopsQuery.data.queue_count ?? 0}</p>
              <p>memory entries: {gitopsQuery.data.memory_count ?? 0}</p>
            </div>
          ) : undefined}
        </DataPanel>

        <DataPanel title="Workflows" loading={workflowsQuery.isLoading}>
          {workflowsQuery.data ? (
            <p className="text-xs text-slate-300">registered workflows: {workflowsQuery.data.count ?? 0}</p>
          ) : undefined}
        </DataPanel>

        <DataPanel title="Scriptlib" loading={scriptlibQuery.isLoading}>
          {scriptlibQuery.data ? (
            <div className="space-y-1 text-xs text-slate-300">
              <p>root: {scriptlibQuery.data.root ?? "not configured"}</p>
              <p>enabled: {scriptlibQuery.data.exists ? "yes" : "no"}</p>
            </div>
          ) : undefined}
        </DataPanel>
      </main>
    </div>
  );
}

export default function App() {
  return (
    <AuthGate>
      <PilotDeck />
    </AuthGate>
  );
}
