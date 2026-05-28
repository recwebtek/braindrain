import { render, screen } from "@testing-library/react";
import { NexusDashboard } from "@/components/NexusDashboard";

vi.mock("@livingdash/ui-shared", () => {
  return {
    useOverviewQuery: () => ({
      isLoading: false,
      data: {
        version: "2.1",
        workspace: { name: "demo", project_name: "BRAIN_MCP_HUB", branch: "main" },
        repo_brief: { title: "t", summary: "s", entrypoint: "e", posture: "p" },
        facts: [{ label: "a", value: "1", tone: "cyan" }],
        systems: [],
        startup_flow: [],
        kpis: [],
        recent_activity: [],
        shortcuts: [],
        map_access: { label: "m", description: "d", cta: "c" },
      },
    }),
    useAgentsQuery: () => ({ isLoading: false, data: { version: "2.1", count: 2, template_count: 3, items: [] } }),
    usePlansQuery: () => ({ isLoading: false, data: { version: "2.1", cursor_plans: [], updated_at: "now" } }),
    useGitopsQuery: () => ({ isLoading: false, data: { version: "2.1", queue_count: 1, memory_count: 4 } }),
    useWorkflowsQuery: () => ({ isLoading: false, data: { version: "2.1", count: 2, items: [] } }),
    useMCPCatalogQuery: () => ({ isLoading: false, data: { version: "2.1", server_count: 3, configured_tools: [] } }),
    useSessionsQuery: () => ({ isLoading: false, data: { version: "2.1", count: 9, db_path: "/tmp/sessions.sqlite" } }),
    useTelemetryQuery: () => ({
      isLoading: false,
      data: {
        version: "2.1",
        summary: {
          active_tools: 1,
          agents_online: 2,
          refresh_age_seconds: 15,
          token_saving_active: true,
          env_drift: 0,
          recent_action_count: 3,
        },
        events: [],
      },
    }),
    useTestsQuery: () => ({ isLoading: false, data: { version: "2.1", python_test_count: 5, python_tests: [], scripts: [], ci_workflows: [] } }),
  };
});

describe("NexusDashboard", () => {
  it("renders mission control shell", () => {
    render(<NexusDashboard />);
    expect(screen.getByRole("main", { name: /nexus mission control/i })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /nexus force graph/i })).toBeInTheDocument();
    expect(screen.getByText(/spatial mission control/i)).toBeInTheDocument();
  });
});
