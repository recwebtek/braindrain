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

export function BraindrainLogsPage({ data }: { data: BraindrainLogsContract }) {
  const [tab, setTab] = useState<"observer" | "session" | "checkpoints">("observer");
  const observerEvents = data.observer?.events ?? [];
  const sessionEvents = data.session_jsonl?.recent_events ?? [];
  const checkpoints = data.token_checkpoints ?? [];

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
        {tab === "observer" ? (
          <OutputViewer
            stdout={JSON.stringify({ stats: data.observer?.stats, events: observerEvents.slice(0, 40) }, null, 2)}
          />
        ) : null}
        {tab === "session" ? <OutputViewer stdout={JSON.stringify(sessionEvents.slice(-40), null, 2)} /> : null}
        {tab === "checkpoints" ? <OutputViewer stdout={JSON.stringify(checkpoints, null, 2)} /> : null}
      </div>
    </Panel>
  );
}

export function PrimerPage({ data }: { data: PrimerContract }) {
  const primer = data.primer ?? {};
  return (
    <Panel className="p-5" glow>
      <SectionHeader eyebrow="Primer" title="Workspace primer state" detail="Dotfiles, bundle, and last primed metadata (read-only)." />
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <StateBlock title="Last primed" detail={String(primer.last_primed_at ?? "—")} tone="violet" />
        <StateBlock title="Bundle" detail={String(primer.bundle ?? "—")} tone="cyan" />
      </div>
      <div className="mt-4 grid gap-2">
        {(primer.dotfiles ?? []).map((item) => (
          <div key={item.name} className="ld-soft-block flex items-center justify-between p-3">
            <span className="text-sm text-white">{item.name}</span>
            <ToneChip label={item.exists ? "present" : "missing"} tone={item.exists ? "emerald" : "rose"} />
          </div>
        ))}
      </div>
    </Panel>
  );
}

export function ConfigPage({ data }: { data: ConfigPageContract }) {
  const [tab, setTab] = useState<"hub" | "memory">("hub");
  const memory = data.memory?.files ?? {};
  return (
    <Panel className="p-5" glow>
      <SectionHeader
        eyebrow="Config"
        title="Braindrain configuration"
        detail="Read-only hub config summary and project memory excerpts. Export via browser copy."
      />
      <p className="ld-copy mt-2">Mode: read-only (v1)</p>
      <div className="mt-4 flex gap-2">
        <button type="button" className={`ld-tab ${tab === "hub" ? "ld-tab-active" : ""}`} onClick={() => setTab("hub")}>
          Hub config
        </button>
        <button type="button" className={`ld-tab ${tab === "memory" ? "ld-tab-active" : ""}`} onClick={() => setTab("memory")}>
          Memory files
        </button>
      </div>
      <div className="mt-4">
        {tab === "hub" ? <OutputViewer stdout={JSON.stringify(data.hub_config?.tree ?? {}, null, 2)} /> : null}
        {tab === "memory" ? (
          <div className="space-y-4">
            {Object.entries(memory).map(([key, file]) => (
              <MarkdownPanel key={key} title={key} content={file.excerpt || "(missing)"} />
            ))}
          </div>
        ) : null}
      </div>
    </Panel>
  );
}

export function AgentsPage({ data }: { data: AgentsContract }) {
  const [selected, setSelected] = useState<string | null>(null);
  const detail = data.items.find((item) => item.name === selected);
  return (
    <Panel className="p-5" glow>
      <SectionHeader eyebrow="Agents" title="Installed agents" detail={`${data.count} installed · ${data.template_count} templates`} />
      <div className="mt-4 grid gap-4 xl:grid-cols-[1fr_1fr]">
        <div className="space-y-2">
          {data.items.map((agent) => (
            <button
              key={`${agent.provider}-${agent.name}`}
              type="button"
              className="ld-soft-block w-full p-3 text-left"
              onClick={() => setSelected(agent.name)}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium text-white">{agent.name}</span>
                <ToneChip label={agent.installed ? "installed" : "template"} tone={agent.installed ? "emerald" : "amber"} />
              </div>
              <p className="ld-copy mt-2">{agent.model ?? "model: —"} · {agent.provider}</p>
            </button>
          ))}
        </div>
        <div className="ld-surface p-4">
          {detail ? (
            <>
              <h3 className="text-lg font-semibold text-white">{detail.name}</h3>
              <p className="ld-copy mt-2">{detail.description || "No description"}</p>
              <p className="ld-copy mt-2">Hooks: {(detail.hooks ?? []).join(", ") || "—"}</p>
              <p className="ld-copy mt-2">Path: {detail.path}</p>
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
            {(data.installed ?? []).map((skill) => (
              <div key={skill.path} className="ld-soft-block p-3">
                <span className="font-medium text-white">{skill.name}</span>
                <p className="ld-copy mt-1">{skill.excerpt}</p>
              </div>
            ))}
          </div>
        </div>
        <div>
          <h3 className="text-sm font-semibold text-white">Template drift</h3>
          <div className="mt-2 flex flex-wrap gap-2">
            {(data.drift_missing ?? []).map((name) => (
              <ToneChip key={name} label={name} tone="amber" />
            ))}
          </div>
        </div>
      </div>
    </Panel>
  );
}

export function PlansPage({ data }: { data: PlansContract }) {
  const cursorPlans = data.cursor_plans ?? [];
  return (
    <Panel className="p-5" glow>
      <SectionHeader eyebrow="Plans" title="Planning master data" detail="Master plan, next-actions queue, and audit freshness." />
      <div className="mt-4 space-y-4">
        {cursorPlans.length > 0 ? (
          <div className="ld-surface p-4">
            <h3 className="text-sm font-semibold text-white">Cursor plans ({cursorPlans.length})</h3>
            <div className="mt-3 overflow-x-auto">
              <table className="w-full text-left text-xs">
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
                    <tr key={plan.path} className="border-t border-white/6">
                      <td className="py-2 pr-3 text-white">{plan.name}</td>
                      <td className="py-2 pr-3">
                        <ToneChip label={plan.archived ? "archived" : plan.disposition} tone={plan.archived ? "amber" : "emerald"} />
                      </td>
                      <td className="py-2 pr-3 text-[color:var(--ld-text-soft)]">{plan.branch ?? "—"}</td>
                      <td className="py-2 font-mono text-[10px] text-[color:var(--ld-text-muted)]">{plan.path}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ) : null}
        <MarkdownPanel title="Master plan" content={data.master_plan?.excerpt ?? ""} />
        <MarkdownPanel title="Next actions" content={data.next_actions?.excerpt ?? ""} />
        <StateBlock title="Audit files" detail={(data.audit_files ?? []).join(", ") || "—"} tone="cyan" />
      </div>
    </Panel>
  );
}

export function TestsPage({ data }: { data: TestsContract }) {
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
          <ul className="ld-copy mt-2 list-disc pl-5">
            {(data.python_tests ?? []).map((file) => (
              <li key={file}>{file}</li>
            ))}
          </ul>
          <h3 className="mt-4 text-sm font-semibold text-white">Run scripts</h3>
          <div className="mt-2 space-y-2">
            {(data.scripts ?? []).map((script) => (
              <div key={script.id} className="ld-soft-block p-3">
                <span className="text-white">{script.label}</span>
                <p className="ld-copy mt-1">{script.command}</p>
              </div>
            ))}
          </div>
        </div>
        <div>
          <h3 className="text-sm font-semibold text-white">CI workflows</h3>
          <div className="mt-2 space-y-3">
            {(data.ci_workflows ?? []).map((wf) => (
              <div key={wf.file} className="ld-soft-block p-3">
                <span className="font-medium text-white">{wf.file}</span>
                <p className="ld-copy mt-1">Jobs: {(wf.jobs ?? []).join(", ") || "—"}</p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </Panel>
  );
}
