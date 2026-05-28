import {
  useAgentsQuery,
  useGitopsQuery,
  useMCPCatalogQuery,
  useOverviewQuery,
  usePlansQuery,
  useSessionsQuery,
  useTelemetryQuery,
  useTestsQuery,
  useWorkflowsQuery,
} from "@livingdash/ui-shared";
import type { GraphEdge, GraphNode } from "@/components/ForceGraphPanel";
import { ForceGraphPanel } from "@/components/ForceGraphPanel";

interface DomainCard {
  id: string;
  label: string;
  metric: string;
  detail: string;
}

export function NexusDashboard() {
  const overview = useOverviewQuery();
  const agents = useAgentsQuery();
  const plans = usePlansQuery();
  const gitops = useGitopsQuery();
  const workflows = useWorkflowsQuery();
  const mcpCatalog = useMCPCatalogQuery();
  const sessions = useSessionsQuery(40);
  const telemetry = useTelemetryQuery();
  const tests = useTestsQuery();

  const loading = [
    overview.isLoading,
    agents.isLoading,
    plans.isLoading,
    gitops.isLoading,
    workflows.isLoading,
    mcpCatalog.isLoading,
    sessions.isLoading,
    telemetry.isLoading,
    tests.isLoading,
  ].some(Boolean);

  const domainCards: DomainCard[] = [
    {
      id: "overview",
      label: "Overview",
      metric: `${overview.data?.facts.length ?? 0} facts`,
      detail: overview.data?.workspace.project_name ?? "No workspace signal yet",
    },
    {
      id: "agents",
      label: "Agents",
      metric: `${agents.data?.count ?? 0} active`,
      detail: `${agents.data?.template_count ?? 0} templates`,
    },
    {
      id: "plans",
      label: "Plans",
      metric: `${overviewCount(plans.data?.cursor_plans)} open`,
      detail: plans.data?.updated_at ? `Updated ${plans.data.updated_at}` : "Awaiting planner output",
    },
    {
      id: "gitops",
      label: "GitOps",
      metric: `${gitops.data?.queue_count ?? 0} queued`,
      detail: `${gitops.data?.memory_count ?? 0} memory entries`,
    },
    {
      id: "workflows",
      label: "Workflows",
      metric: `${workflows.data?.count ?? overviewCount(workflows.data?.items)} registered`,
      detail: workflows.data?.updated_at ? `Updated ${workflows.data.updated_at}` : "No workflow updates",
    },
    {
      id: "mcp-catalog",
      label: "MCP Catalog",
      metric: `${mcpCatalog.data?.server_count ?? 0} servers`,
      detail: `${overviewCount(mcpCatalog.data?.configured_tools)} configured tools`,
    },
    {
      id: "sessions",
      label: "Sessions",
      metric: `${sessions.data?.count ?? 0} observed`,
      detail: sessions.data?.db_path ?? "No session database path",
    },
    {
      id: "telemetry",
      label: "Telemetry",
      metric: `${telemetry.data?.summary.agents_online ?? 0} online`,
      detail: `${telemetry.data?.summary.recent_action_count ?? 0} recent actions`,
    },
    {
      id: "tests",
      label: "Tests",
      metric: `${tests.data?.python_test_count ?? 0} python`,
      detail: `${overviewCount(tests.data?.ci_workflows)} CI workflows`,
    },
  ];

  const graphNodes: GraphNode[] = buildGraphNodes(domainCards);
  const graphEdges: GraphEdge[] = buildGraphEdges(graphNodes);

  return (
    <main className="nexus-root" aria-label="Nexus mission control">
      <section className="nexus-hero">
        <div>
          <p className="nexus-eyebrow">LIVINGDASH NEXUS</p>
          <h1>Spatial mission control</h1>
          <p>
            Domains are rendered as a connected graph sourced from overview, agents, plans, gitops, workflows, MCP catalog, sessions,
            telemetry, and tests.
          </p>
        </div>
        <div className="nexus-hero-kpi">
          <span>Signal freshness</span>
          <strong>{telemetry.data?.summary.refresh_age_seconds ?? 0}s</strong>
        </div>
      </section>

      <ForceGraphPanel nodes={graphNodes} edges={graphEdges} loading={loading} />

      <section className="nexus-grid" aria-label="Nexus domain cards">
        {loading ? (
          <div className="nexus-empty">Loading domain telemetry...</div>
        ) : (
          domainCards.map((card) => (
            <article key={card.id} className="nexus-card">
              <p className="nexus-card-label">{card.label}</p>
              <h3>{card.metric}</h3>
              <p>{card.detail}</p>
            </article>
          ))
        )}
      </section>
    </main>
  );
}

function buildGraphNodes(cards: DomainCard[]): GraphNode[] {
  if (!cards.length) {
    return [];
  }

  const hub: GraphNode = {
    id: "nexus-hub",
    label: "NEXUS",
    value: cards.length,
    tone: "cyan",
  };

  const perDomainNodes: GraphNode[] = cards.map((card, index) => ({
    id: card.id,
    label: card.label,
    value: metricToValue(card.metric),
    tone: pickTone(index),
  }));

  return [hub, ...perDomainNodes];
}

function buildGraphEdges(nodes: GraphNode[]): GraphEdge[] {
  if (nodes.length < 2) {
    return [];
  }

  const [hub, ...domains] = nodes;
  const hubEdges = domains.map((domain, index) => ({
    id: `hub-${domain.id}`,
    source: hub.id,
    target: domain.id,
    weight: Math.max(2, Math.round(domain.value / 8) + (index % 3)),
  }));

  const meshEdges = domains.slice(1).map((domain, index) => ({
    id: `mesh-${domains[index].id}-${domain.id}`,
    source: domains[index].id,
    target: domain.id,
    weight: 1 + ((index + domain.value) % 3),
  }));

  return [...hubEdges, ...meshEdges];
}

function overviewCount(value: unknown): number {
  return Array.isArray(value) ? value.length : 0;
}

function metricToValue(metric: string): number {
  const parsed = Number.parseInt(metric, 10);
  if (Number.isFinite(parsed)) {
    return parsed;
  }
  return 1;
}

function pickTone(index: number): GraphNode["tone"] {
  const tones: GraphNode["tone"][] = ["cyan", "violet", "emerald", "amber"];
  return tones[index % tones.length];
}
