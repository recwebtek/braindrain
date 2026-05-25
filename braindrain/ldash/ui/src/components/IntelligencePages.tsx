import { useState } from "react";
import type {
  AgentsContract,
  BraindrainLogsContract,
  ConfigPageContract,
  PlansContract,
  PrimerContract,
  SkillsContract,
  TestsContract,
} from "@/data";
import { MarkdownPanel, OutputViewer, Panel, SectionHeader, StateBlock, ToneChip } from "@/components/ldash/Primitives";
import {
  EmptyAgentsState,
  EmptySkillsState,
  EmptyPlansState,
  EmptyLogsState,
  EmptyConfigState,
  EmptyPrimerState,
  EmptyTestsState,
  EmptyGitState,
} from "@/components/ldash/EmptyState";

export function BraindrainLogsPage({ data }: { data: BraindrainLogsContract }) {
  const [tab, setTab] = useState<"observer" | "session" | "checkpoints">("observer");
  const observerEvents = data.observer?.events ?? [];
  const sessionEvents = data.session_jsonl?.recent_events ?? [];
  const checkpoints = data.token_checkpoints ?? [];

  // Check if all data is empty
  const hasNoData = observerEvents.length === 0 && sessionEvents.length === 0 && checkpoints.length === 0;

  return (
    <Panel className="p-5" glow>
      <SectionHeader
        eyebrow="Braindrain"
        title="MCP log explorer"
        detail="Read-only view of observer SQLite events, session JSONL, and token checkpoints."
      />
      <div className="mt-4 flex flex-wrap gap-2">
        {(["observer", "session", "checkpoints"] as const).map((item) => (
          <button key={item} type="button" className={`ld-tab ${tab === item ? "ld-tab-active" : ""}`} onClick={() => setTab(item)}>
            {item}
          </button>
        ))}
      </div>
      <div className="mt-4">
        {hasNoData ? (
          <EmptyLogsState />
        ) : (
          <>
            {tab === "observer" ? (
              observerEvents.length === 0 ? (
                <EmptyLogsState />
              ) : (
                <OutputViewer
                  stdout={JSON.stringify({ stats: data.observer?.stats, events: observerEvents.slice(0, 40) }, null, 2)}
                />
              )
            ) : null}
            {tab === "session" ? (
              sessionEvents.length === 0 ? (
                <p className="ld-copy text-center py-8">No session events recorded yet.</p>
              ) : (
                <OutputViewer stdout={JSON.stringify(sessionEvents.slice(-40), null, 2)} />
              )
            ) : null}
            {tab === "checkpoints" ? (
              checkpoints.length === 0 ? (
                <p className="ld-copy text-center py-8">No token checkpoints available.</p>
              ) : (
                <OutputViewer stdout={JSON.stringify(checkpoints, null, 2)} />
              )
            ) : null}
          </>
        )}
      </div>
    </Panel>
  );
}

export function PrimerPage({ data }: { data: PrimerContract }) {
  const primer = data.primer ?? {};
  const isEmpty = !primer.last_primed_at && !primer.bundle;

  return (
    <Panel className="p-5" glow>
      <SectionHeader eyebrow="Primer" title="Workspace primer state" detail="Dotfiles, bundle, and last primed metadata (read-only)." />
      {isEmpty ? (
        <div className="mt-4">
          <EmptyPrimerState />
        </div>
      ) : (
        <>
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <StateBlock title="Last primed" detail={String(primer.last_primed_at ?? "—")} tone="violet" />
            <StateBlock title="Bundle" detail={String(primer.bundle ?? "—")} tone="cyan" />
          </div>
          <div className="mt-4 grid gap-2">
            {(primer.dotfiles ?? []).map((item) => (
              <div key={item.name} className="ld-soft-block flex items-center justify-between p-3 hover:bg-white/5 transition-colors">
                <span className="text-sm text-white">{item.name}</span>
                <ToneChip label={item.exists ? "present" : "missing"} tone={item.exists ? "emerald" : "rose"} />
              </div>
            ))}
          </div>
        </>
      )}
    </Panel>
  );
}

export function ConfigPage({ data }: { data: ConfigPageContract }) {
  const [tab, setTab] = useState<"hub" | "memory">("hub");
  const memory = data.memory?.files ?? {};
  const hasHubConfig = Object.keys(data.hub_config?.tree ?? {}).length > 0;
  const hasMemory = Object.keys(memory).length > 0;

  return (
    <Panel className="p-5" glow>
      <SectionHeader
        eyebrow="Config"
        title="Braindrain configuration"
        detail="Read-only hub config summary and project memory excerpts. Export via browser copy."
      />
      <p className="ld-copy mt-2">Mode: read-only (v1)</p>
      <div className="mt-4 flex flex-wrap gap-2">
        <button type="button" className={`ld-tab min-h-[44px] ${tab === "hub" ? "ld-tab-active" : ""}`} onClick={() => setTab("hub")}>
          Hub config
        </button>
        <button type="button" className={`ld-tab min-h-[44px] ${tab === "memory" ? "ld-tab-active" : ""}`} onClick={() => setTab("memory")}>
          Memory files
        </button>
      </div>
      <div className="mt-4">
        {tab === "hub" ? (
          hasHubConfig ? (
            <OutputViewer stdout={JSON.stringify(data.hub_config?.tree ?? {}, null, 2)} />
          ) : (
            <EmptyConfigState />
          )
        ) : null}
        {tab === "memory" ? (
          hasMemory ? (
            <div className="space-y-4">
              {Object.entries(memory).map(([key, file]) => (
                <MarkdownPanel key={key} title={key} content={file.excerpt || "(missing)"} />
              ))}
            </div>
          ) : (
            <EmptyConfigState />
          )
        ) : null}
      </div>
    </Panel>
  );
}

export function AgentsPage({ data }: { data: AgentsContract }) {
  const [selected, setSelected] = useState<string | null>(null);
  const detail = data.items.find((item) => item.name === selected);

  // Show empty state if no agents
  if (data.items.length === 0) {
    return (
      <Panel className="p-5" glow>
        <SectionHeader eyebrow="Agents" title="Installed agents" detail="0 installed" />
        <div className="mt-4">
          <EmptyAgentsState />
        </div>
      </Panel>
    );
  }

  return (
    <Panel className="p-5" glow>
      <SectionHeader eyebrow="Agents" title="Installed agents" detail={`${data.count} installed · ${data.template_count} templates`} />
      <div className="mt-4 grid gap-4 xl:grid-cols-[1fr_1fr]">
        <div className="space-y-2 max-h-[60vh] overflow-auto pr-1">
          {data.items.map((agent) => (
            <button
              key={`${agent.provider}-${agent.name}`}
              type="button"
              className={`ld-soft-block w-full p-3 text-left min-h-[44px] transition-all duration-200 hover:bg-white/5 hover:border-[color:var(--ld-brand-500)]/30 ${
                selected === agent.name ? "bg-white/10 border-[color:var(--ld-brand-500)]/50" : ""
              }`}
              onClick={() => setSelected(agent.name)}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium text-white truncate">{agent.name}</span>
                <ToneChip label={agent.installed ? "installed" : "template"} tone={agent.installed ? "emerald" : "amber"} />
              </div>
              <p className="ld-copy mt-2 truncate">{agent.model ?? "model: —"} · {agent.provider}</p>
            </button>
          ))}
        </div>
        <div className="ld-surface p-4 min-h-[200px]">
          {detail ? (
            <>
              <h3 className="text-lg font-semibold text-white">{detail.name}</h3>
              <p className="ld-copy mt-2">{detail.description || "No description"}</p>
              <p className="ld-copy mt-2 text-[color:var(--ld-text-muted)]">Hooks: {(detail.hooks ?? []).join(", ") || "—"}</p>
              <p className="ld-copy mt-2 text-[color:var(--ld-text-muted)] break-all">Path: {detail.path}</p>
            </>
          ) : (
            <StateBlock title="Select an agent" detail="Choose a row to inspect capabilities and hooks." tone="violet" />
          )}
        </div>
      </div>
    </Panel>
  );
}

export function SkillsPage({ data }: { data: SkillsContract }) {
  // Show empty state if no skills installed
  if (data.installed_count === 0 && (data.templates ?? []).length === 0) {
    return (
      <Panel className="p-5" glow>
        <SectionHeader eyebrow="Skills" title="Installed skills" detail="0 installed" />
        <div className="mt-4">
          <EmptySkillsState />
        </div>
      </Panel>
    );
  }

  return (
    <Panel className="p-5" glow>
      <SectionHeader
        eyebrow="Skills"
        title="Installed skills"
        detail={`${data.installed_count} installed · drift: ${(data.drift_missing ?? []).length} missing templates`}
      />
      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <div>
          <h3 className="text-sm font-semibold text-white">Installed</h3>
          <div className="mt-2 space-y-2">
            {(data.installed ?? []).length === 0 ? (
              <p className="ld-copy py-4 text-center">No skills installed.</p>
            ) : (
              (data.installed ?? []).map((skill) => (
                <div key={skill.path} className="ld-soft-block p-3 hover:bg-white/5 transition-colors">
                  <span className="font-medium text-white">{skill.name}</span>
                  <p className="ld-copy mt-1 line-clamp-2">{skill.excerpt}</p>
                </div>
              ))
            )}
          </div>
        </div>
        <div>
          <h3 className="text-sm font-semibold text-white">Template drift</h3>
          <div className="mt-2 flex flex-wrap gap-2">
            {(data.drift_missing ?? []).length === 0 ? (
              <p className="ld-copy py-4">No drift detected.</p>
            ) : (
              (data.drift_missing ?? []).map((name) => (
                <ToneChip key={name} label={name} tone="amber" />
              ))
            )}
          </div>
        </div>
      </div>
    </Panel>
  );
}

export function PlansPage({ data }: { data: PlansContract }) {
  const cursorPlans = data.cursor_plans ?? [];
  const hasMasterPlan = data.master_plan?.excerpt && data.master_plan.excerpt.length > 0;
  const hasNextActions = data.next_actions?.excerpt && data.next_actions.excerpt.length > 0;
  const isEmpty = cursorPlans.length === 0 && !hasMasterPlan && !hasNextActions;

  if (isEmpty) {
    return (
      <Panel className="p-5" glow>
        <SectionHeader eyebrow="Plans" title="Planning master data" detail="Master plan, next-actions queue, and audit freshness." />
        <div className="mt-4">
          <EmptyPlansState />
        </div>
      </Panel>
    );
  }

  return (
    <Panel className="p-5" glow>
      <SectionHeader eyebrow="Plans" title="Planning master data" detail="Master plan, next-actions queue, and audit freshness." />
      <div className="mt-4 space-y-4">
        {cursorPlans.length > 0 ? (
          <div className="ld-surface p-4 overflow-hidden">
            <h3 className="text-sm font-semibold text-white">Cursor plans ({cursorPlans.length})</h3>
            <div className="mt-3 overflow-x-auto">
              <table className="w-full text-left text-xs min-w-[500px]">
                <thead>
                  <tr className="text-[color:var(--ld-text-soft)]">
                    <th className="pb-2 pr-3 font-semibold">Plan</th>
                    <th className="pb-2 pr-3 font-semibold">Disposition</th>
                    <th className="pb-2 pr-3 font-semibold">Branch</th>
                    <th className="pb-2 font-semibold">Path</th>
                  </tr>
                </thead>
                <tbody>
                  {cursorPlans.map((plan) => (
                    <tr key={plan.path} className="border-t border-white/6 hover:bg-white/5 transition-colors">
                      <td className="py-2 pr-3 text-white">{plan.name}</td>
                      <td className="py-2 pr-3">
                        <ToneChip label={plan.archived ? "archived" : plan.disposition} tone={plan.archived ? "amber" : "emerald"} />
                      </td>
                      <td className="py-2 pr-3 text-[color:var(--ld-text-soft)]">{plan.branch ?? "—"}</td>
                      <td className="py-2 font-mono text-[10px] text-[color:var(--ld-text-muted)] truncate max-w-[200px]">{plan.path}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ) : null}
        {hasMasterPlan && <MarkdownPanel title="Master plan" content={data.master_plan?.excerpt ?? ""} />}
        {hasNextActions && <MarkdownPanel title="Next actions" content={data.next_actions?.excerpt ?? ""} />}
        {(data.audit_files ?? []).length > 0 && (
          <StateBlock title="Audit files" detail={(data.audit_files ?? []).join(", ")} tone="cyan" />
        )}
      </div>
    </Panel>
  );
}

export function TestsPage({ data }: { data: TestsContract }) {
  const isEmpty = data.python_test_count === 0 && (data.ci_workflows ?? []).length === 0 && (data.scripts ?? []).length === 0;

  if (isEmpty) {
    return (
      <Panel className="p-5" glow>
        <SectionHeader eyebrow="Tests" title="Workspace & CI tests" detail="0 tests found" />
        <div className="mt-4">
          <EmptyTestsState />
        </div>
      </Panel>
    );
  }

  return (
    <Panel className="p-5" glow>
      <SectionHeader
        eyebrow="Tests"
        title="Workspace & CI tests"
        detail={`${data.python_test_count} Python tests · ${(data.ci_workflows ?? []).length} CI workflows`}
      />
      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <div>
          <h3 className="text-sm font-semibold text-white">Python tests</h3>
          {(data.python_tests ?? []).length === 0 ? (
            <p className="ld-copy py-4 text-[color:var(--ld-text-muted)]">No Python tests found.</p>
          ) : (
            <ul className="ld-copy mt-2 list-disc pl-5 space-y-1">
              {(data.python_tests ?? []).map((file) => (
                <li key={file} className="break-all">{file}</li>
              ))}
            </ul>
          )}
          <h3 className="mt-4 text-sm font-semibold text-white">Run scripts</h3>
          <div className="mt-2 space-y-2">
            {(data.scripts ?? []).length === 0 ? (
              <p className="ld-copy py-2 text-[color:var(--ld-text-muted)]">No scripts configured.</p>
            ) : (
              (data.scripts ?? []).map((script) => (
                <div key={script.id} className="ld-soft-block p-3 hover:bg-white/5 transition-colors">
                  <span className="text-white font-medium">{script.label}</span>
                  <p className="ld-copy mt-1 break-all font-mono text-xs">{script.command}</p>
                </div>
              ))
            )}
          </div>
        </div>
        <div>
          <h3 className="text-sm font-semibold text-white">CI workflows</h3>
          <div className="mt-2 space-y-3">
            {(data.ci_workflows ?? []).length === 0 ? (
              <p className="ld-copy py-4 text-[color:var(--ld-text-muted)]">No CI workflows found.</p>
            ) : (
              (data.ci_workflows ?? []).map((wf) => (
                <div key={wf.file} className="ld-soft-block p-3 hover:bg-white/5 transition-colors">
                  <span className="font-medium text-white">{wf.file}</span>
                  <p className="ld-copy mt-1">Jobs: {(wf.jobs ?? []).join(", ") || "—"}</p>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </Panel>
  );
}
