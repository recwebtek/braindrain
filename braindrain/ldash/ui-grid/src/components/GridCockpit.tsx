import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  defaultClient,
} from "@livingdash/ui-shared";

type Primitive = string | number | boolean | null | undefined;
type GenericRecord = Record<string, unknown>;
type SortDirection = "asc" | "desc";

interface ColumnDef {
  key: string;
  label: string;
}

interface TablePanelProps {
  title: string;
  subtitle: string;
  rows: GenericRecord[];
  columns: ColumnDef[];
  loading: boolean;
}

const FALLBACK_COLUMNS: ColumnDef[] = [
  { key: "label", label: "Label" },
  { key: "value", label: "Value" },
];

function toRows(input: unknown): GenericRecord[] {
  if (Array.isArray(input)) {
    return input.filter((value): value is GenericRecord => typeof value === "object" && value !== null) as GenericRecord[];
  }
  return [];
}

function toPairs(input: unknown): GenericRecord[] {
  if (!input || typeof input !== "object" || Array.isArray(input)) {
    return [];
  }
  return Object.entries(input as GenericRecord).map(([key, value]) => ({
    key,
    value: stringify(value),
  }));
}

function stringify(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return value.map((item) => stringify(item)).join(", ");
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function valueForSort(value: unknown): Primitive {
  if (typeof value === "number" || typeof value === "boolean") return value;
  if (typeof value === "string") return value.toLowerCase();
  return stringify(value).toLowerCase();
}

function pickColumns(rows: GenericRecord[], fallback: ColumnDef[] = FALLBACK_COLUMNS): ColumnDef[] {
  const firstRow = rows[0];
  if (!firstRow) return fallback;
  const keys = Object.keys(firstRow).slice(0, 6);
  if (!keys.length) return fallback;
  return keys.map((key) => ({ key, label: key.replaceAll("_", " ") }));
}

function TablePanel({ title, subtitle, rows, columns, loading }: TablePanelProps) {
  const [filterText, setFilterText] = useState("");
  const [sortKey, setSortKey] = useState(columns[0]?.key ?? "label");
  const [sortDirection, setSortDirection] = useState<SortDirection>("asc");

  const visibleRows = useMemo(() => {
    const needle = filterText.trim().toLowerCase();
    const filtered = !needle
      ? rows
      : rows.filter((row) => columns.some((column) => stringify(row[column.key]).toLowerCase().includes(needle)));
    const sorted = [...filtered].sort((left, right) => {
      const leftValue = valueForSort(left[sortKey]);
      const rightValue = valueForSort(right[sortKey]);
      if (leftValue === rightValue) return 0;
      if (leftValue > rightValue) return sortDirection === "asc" ? 1 : -1;
      return sortDirection === "asc" ? -1 : 1;
    });
    return sorted;
  }, [columns, filterText, rows, sortDirection, sortKey]);

  const handleSort = (column: string) => {
    if (column === sortKey) {
      setSortDirection((direction) => (direction === "asc" ? "desc" : "asc"));
      return;
    }
    setSortKey(column);
    setSortDirection("asc");
  };

  return (
    <section className="rounded-lg border border-white/10 bg-[var(--ld-panel)] p-3">
      <header className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-[var(--ld-text-primary)]">{title}</h3>
          <p className="text-xs text-[var(--ld-text-secondary)]">{subtitle}</p>
        </div>
        <input
          value={filterText}
          onChange={(event) => setFilterText(event.target.value)}
          placeholder="Filter rows"
          className="h-8 w-44 rounded-md border border-white/10 bg-black/35 px-2 text-xs text-[var(--ld-text-primary)] outline-none focus:border-cyan-400/60"
        />
      </header>
      {loading ? (
        <div className="grid h-48 place-items-center rounded-md border border-dashed border-white/10 text-xs text-[var(--ld-text-secondary)]">
          Loading {title.toLowerCase()}...
        </div>
      ) : visibleRows.length ? (
        <div className="max-h-72 overflow-auto rounded-md border border-white/10">
          <table className="w-full border-collapse text-xs">
            <thead className="sticky top-0 bg-black/70 backdrop-blur">
              <tr>
                {columns.map((column) => (
                  <th key={column.key} className="border-b border-white/10 px-2 py-1 text-left font-medium text-[var(--ld-text-secondary)]">
                    <button className="inline-flex items-center gap-1" type="button" onClick={() => handleSort(column.key)}>
                      <span className="capitalize">{column.label}</span>
                      {sortKey === column.key ? <span>{sortDirection === "asc" ? "▲" : "▼"}</span> : null}
                    </button>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {visibleRows.map((row, index) => (
                <tr key={`${title}-${index}`} className="odd:bg-white/[0.02]">
                  {columns.map((column) => (
                    <td key={`${title}-${index}-${column.key}`} className="border-b border-white/5 px-2 py-1 align-top text-[var(--ld-text-primary)]">
                      {stringify(row[column.key]) || "-"}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="grid h-48 place-items-center rounded-md border border-dashed border-white/10 text-xs text-[var(--ld-text-secondary)]">
          No data available.
        </div>
      )}
    </section>
  );
}

function KpiCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-white/10 bg-black/25 px-3 py-2">
      <p className="text-[11px] uppercase tracking-wide text-[var(--ld-text-secondary)]">{label}</p>
      <p className="mt-1 text-lg font-semibold text-[var(--ld-text-primary)]">{value}</p>
    </div>
  );
}

export function GridCockpit() {
  const overviewQuery = useQuery({
    queryKey: ["livingdash", "overview"],
    queryFn: () => defaultClient.fetchOverview(),
  });
  const telemetryQuery = useQuery({
    queryKey: ["livingdash", "telemetry"],
    queryFn: () => defaultClient.fetchTelemetry(),
  });
  const plansQuery = useQuery({
    queryKey: ["livingdash", "plans"],
    queryFn: () => defaultClient.fetchPlans(),
  });
  const testsQuery = useQuery({
    queryKey: ["livingdash", "tests"],
    queryFn: () => defaultClient.fetchTests(),
  });
  const agentsQuery = useQuery({
    queryKey: ["livingdash", "agents"],
    queryFn: () => defaultClient.fetchAgents(),
  });
  const skillsQuery = useQuery({
    queryKey: ["livingdash", "skills"],
    queryFn: () => defaultClient.fetchSkills(),
  });
  const configQuery = useQuery({
    queryKey: ["livingdash", "config"],
    queryFn: () => defaultClient.fetchConfig(),
  });
  const scriptlibQuery = useQuery({
    queryKey: ["livingdash", "scriptlib"],
    queryFn: () => defaultClient.fetchScriptlib(),
  });
  const sessionsQuery = useQuery({
    queryKey: ["livingdash", "sessions", 50],
    queryFn: () => defaultClient.fetchSessions(50),
  });

  const overviewRows = toRows(overviewQuery.data?.kpis);
  const telemetryRows = toRows(telemetryQuery.data?.events);
  const plansRows = toRows(plansQuery.data?.cursor_plans);
  const testsRows = [
    ...toRows(testsQuery.data?.scripts),
    ...toRows(testsQuery.data?.ci_workflows),
    ...((testsQuery.data?.python_tests ?? []).map((item) => ({ test: item })) as GenericRecord[]),
  ];
  const agentsRows = toRows(agentsQuery.data?.items);
  const skillsRows = [...toRows(skillsQuery.data?.installed), ...toRows(skillsQuery.data?.templates)];
  const configRows = toPairs(configQuery.data?.hub_config);
  const scriptlibRows = [...toPairs(scriptlibQuery.data?.index), ...toPairs(scriptlibQuery.data?.catalog)];
  const sessionsRows = toRows(sessionsQuery.data?.items);

  const kpis = [
    { label: "Branch", value: overviewQuery.data?.workspace.branch ?? "-" },
    { label: "Tools Active", value: String(telemetryQuery.data?.summary.active_tools ?? 0) },
    { label: "Plans", value: String(plansRows.length) },
    { label: "Tests", value: String(testsQuery.data?.python_test_count ?? 0) },
    { label: "Agents", value: String(agentsQuery.data?.count ?? 0) },
    { label: "Skills", value: String(skillsQuery.data?.installed_count ?? 0) },
    { label: "Sessions", value: String(sessionsQuery.data?.count ?? sessionsRows.length) },
  ];

  return (
    <main className="min-h-screen bg-[var(--ld-bg)] p-3 text-[var(--ld-text-primary)]">
      <header className="mb-3 rounded-lg border border-white/10 bg-[var(--ld-panel)] p-3">
        <p className="text-[11px] uppercase tracking-[0.2em] text-[var(--ld-text-secondary)]">LivingDash GRID analyst cockpit</p>
        <h1 className="mt-1 text-xl font-semibold">{overviewQuery.data?.workspace.project_name ?? "Workspace telemetry grid"}</h1>
        <p className="text-xs text-[var(--ld-text-secondary)]">Dense table-centric view across overview, telemetry, plans, tests, agents, skills, config, scriptlib, and sessions.</p>
      </header>

      <section className="mb-3 grid grid-cols-2 gap-2 lg:grid-cols-7">
        {kpis.map((kpi) => (
          <KpiCard key={kpi.label} label={kpi.label} value={kpi.value} />
        ))}
      </section>

      <section className="grid gap-3 lg:grid-cols-2">
        <TablePanel title="Overview KPIs" subtitle="Workspace KPI rows" rows={overviewRows} columns={pickColumns(overviewRows)} loading={overviewQuery.isLoading} />
        <TablePanel
          title="Telemetry Events"
          subtitle="Recent telemetry stream"
          rows={telemetryRows}
          columns={pickColumns(telemetryRows, [
            { key: "event", label: "Event" },
            { key: "value", label: "Value" },
          ])}
          loading={telemetryQuery.isLoading}
        />
        <TablePanel title="Plans" subtitle="Cursor planning records" rows={plansRows} columns={pickColumns(plansRows)} loading={plansQuery.isLoading} />
        <TablePanel title="Tests" subtitle="Python, scripts, CI workflows" rows={testsRows} columns={pickColumns(testsRows)} loading={testsQuery.isLoading} />
        <TablePanel title="Agents" subtitle="Installed agent records" rows={agentsRows} columns={pickColumns(agentsRows)} loading={agentsQuery.isLoading} />
        <TablePanel title="Skills" subtitle="Installed + template skills" rows={skillsRows} columns={pickColumns(skillsRows)} loading={skillsQuery.isLoading} />
        <TablePanel
          title="Config"
          subtitle="hub_config key/value pairs"
          rows={configRows}
          columns={[
            { key: "key", label: "key" },
            { key: "value", label: "value" },
          ]}
          loading={configQuery.isLoading}
        />
        <TablePanel
          title="Scriptlib"
          subtitle="index and catalog snapshots"
          rows={scriptlibRows}
          columns={[
            { key: "key", label: "key" },
            { key: "value", label: "value" },
          ]}
          loading={scriptlibQuery.isLoading}
        />
        <div className="lg:col-span-2">
          <TablePanel title="Sessions" subtitle="Recent persisted sessions" rows={sessionsRows} columns={pickColumns(sessionsRows)} loading={sessionsQuery.isLoading} />
        </div>
      </section>
    </main>
  );
}
