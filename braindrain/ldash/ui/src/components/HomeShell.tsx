import type { DashboardTab, OverviewContract, TelemetryContract } from "@/data";
import { ActionButton, MetricCard, Panel, SectionHeader, ToneChip } from "@/components/ldash/Primitives";
import { toneClass } from "@/theme";

interface HomeShellProps {
  overview: OverviewContract;
  telemetry: TelemetryContract;
  onOpenTab: (tab: DashboardTab) => void;
}

export function HomeShell({ overview, telemetry, onOpenTab }: HomeShellProps) {
  const summary =
    overview.repo_brief.summary.length > 180
      ? `${overview.repo_brief.summary.slice(0, 177).trimEnd()}...`
      : overview.repo_brief.summary;

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1.3fr)_minmax(320px,0.72fr)]">
      <main aria-label="Overview operations" className="space-y-4">
        <Panel className="p-5" glow>
          <SectionHeader
            eyebrow={overview.repo_brief.title}
            title={summary}
            detail="Overview uses the same operator shell as the rest of LivingDash, with repo status, module pivots, and current counters kept in one place."
            action={<ToneChip label={`v${overview.version}`} tone="emerald" />}
          />

          <div className="mt-5 grid gap-3 xl:grid-cols-[minmax(0,1.05fr)_minmax(280px,0.95fr)]">
            <div className="grid gap-3 sm:grid-cols-2">
              <MetricCard label="Entrypoint" value={overview.repo_brief.entrypoint} tone="violet" detail="Primary server surface." />
              <MetricCard label="Posture" value={overview.repo_brief.posture} tone="cyan" detail="Local-first guarded workflow." />
              {overview.systems.map((item) => (
                <MetricCard key={item.label} label={item.label} value={item.value} tone={item.tone} detail={item.detail} />
              ))}
            </div>

            <div className="ld-surface p-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <p className="ld-eyebrow">Workspace brief</p>
                  <h3 className="mt-2 text-xl font-semibold text-white">{overview.workspace.name}</h3>
                </div>
                <ToneChip label={overview.workspace.branch} tone="violet" />
              </div>
              <div className="mt-4 flex flex-wrap gap-2" aria-label="Workspace fact strip">
                {overview.facts.map((fact) => (
                  <span
                    key={`${fact.label}-${fact.value}`}
                    data-testid="fact-chip"
                    className={`inline-flex items-center gap-2 rounded-md px-3 py-1.5 text-xs font-semibold whitespace-nowrap ${toneClass(fact.tone)}`}
                  >
                    <span className="uppercase tracking-[0.16em] opacity-70">{fact.label}</span>
                    <span>{fact.value}</span>
                  </span>
                ))}
              </div>
              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                {overview.kpis.map((kpi) => (
                  <MetricCard key={kpi.label} label={kpi.label} value={kpi.value} tone={kpi.tone} />
                ))}
              </div>
            </div>
          </div>
        </Panel>

        <div className="grid gap-4 xl:grid-cols-[minmax(0,1.05fr)_minmax(300px,0.95fr)]">
          <Panel className="p-5">
            <SectionHeader
              eyebrow="Startup flow"
              title="Operator open sequence"
              detail="The overview no longer gets a special landing treatment. It behaves like an operational module with fast scan depth."
            />
            <ol className="mt-5 grid gap-3">
              {overview.startup_flow.map((step, index) => (
                <li key={step.label} className="ld-soft-block p-4">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div className="flex items-center gap-3">
                      <span className={`rounded-full px-3 py-1 text-sm font-semibold ${toneClass(step.tone)}`}>{index + 1}</span>
                      <span className="text-base font-semibold text-white">{step.label}</span>
                    </div>
                    <span className="text-sm text-[color:var(--ld-text-soft)]">{step.detail}</span>
                  </div>
                </li>
              ))}
            </ol>
          </Panel>

          <Panel className="p-5">
            <SectionHeader
              eyebrow="Module pivots"
              title="Jump straight into an action surface"
              detail="Existing modules and API contracts stay unchanged; the overview just routes into them from the same shell."
            />
            <div className="mt-5 grid gap-3">
              {overview.shortcuts.map((shortcut) => (
                <ActionButton
                  key={shortcut.id}
                  label={shortcut.label}
                  detail={shortcut.detail}
                  tone={shortcut.tone}
                  onClick={() => onOpenTab(shortcut.id)}
                />
              ))}
            </div>
          </Panel>
        </div>
      </main>

      <aside aria-label="Overview signal rail" className="space-y-4">
        <Panel className="p-5">
          <SectionHeader
            eyebrow="Telemetry"
            title="Live counters"
            detail={`Refresh age ${telemetry.summary.refresh_age_seconds}s`}
            action={<ToneChip label={telemetry.summary.token_saving_active ? "saving" : "idle"} tone="emerald" />}
          />
          <div className="mt-5 grid gap-2.5">
            <MetricCard label="Active tools" value={String(telemetry.summary.active_tools)} tone="emerald" />
            <MetricCard label="Agents online" value={String(telemetry.summary.agents_online)} tone="cyan" />
            <MetricCard label="Recent actions" value={String(telemetry.summary.recent_action_count)} tone="violet" />
            <MetricCard label="Env drift" value={String(telemetry.summary.env_drift)} tone="amber" />
          </div>
        </Panel>

        <Panel className="p-5">
          <SectionHeader
            eyebrow="Recent activity"
            title="Latest approved work"
            detail={`Project ${overview.workspace.project_name}`}
          />
          <div className="mt-5 grid gap-3">
            {overview.recent_activity.length ? (
              overview.recent_activity.map((item) => (
                <div key={`${item.label}-${item.detail}`} className="ld-soft-block p-4">
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-sm font-medium text-white">{item.label}</span>
                    <ToneChip label={item.tone === "rose" ? "attention" : "healthy"} tone={item.tone} />
                  </div>
                  <p className="ld-copy mt-3">{item.detail}</p>
                </div>
              ))
            ) : (
              <div className="ld-soft-block border-dashed p-4 text-sm text-[color:var(--ld-text-soft)]">
                No actions have been recorded yet.
              </div>
            )}
          </div>
        </Panel>

        <Panel className="p-5">
          <SectionHeader eyebrow={overview.map_access.label} title="Secondary topology access" detail={overview.map_access.description} />
          <button className="ld-secondary-button mt-4 w-full" type="button" onClick={() => onOpenTab("plans")}>
            {overview.map_access.cta}
          </button>
        </Panel>
      </aside>
    </div>
  );
}
