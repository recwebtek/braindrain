import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { DashboardWorkspace } from "@/components/DashboardWorkspace";
import { ToastProvider } from "@/components/ldash/Toast";
import { KeyboardProvider } from "@/components/ldash/KeyboardShortcuts";

vi.mock("@/api", async () => {
  const data = await import("@/data");
  const { intelligenceFallbacks } = await vi.importActual<typeof import("@/api")>("@/api");
  return {
    fetchOverview: vi.fn().mockResolvedValue(data.fallbackOverview),
    fetchCommands: vi.fn().mockResolvedValue(data.fallbackCommands),
    fetchGit: vi.fn().mockResolvedValue(data.fallbackGit),
    fetchProcesses: vi.fn().mockResolvedValue(data.fallbackProcesses),
    fetchTelemetry: vi.fn().mockResolvedValue(data.fallbackTelemetry),
    runCommand: vi.fn().mockResolvedValue({
      ok: true,
      status: "success",
      message: "Run UI tests completed",
      updated_at: "just now",
      command_run: {
        id: "ui_tests",
        label: "Run UI tests",
        category: "quality",
        cwd: "braindrain/ldash/ui",
        ok: true,
        status: "success",
        returncode: 0,
        duration_ms: 1234,
        stdout: "ok",
        stderr: "",
        finished_at: "just now",
      },
    }),
    runGitAction: vi.fn().mockResolvedValue({
      ok: true,
      status: "success",
      message: "git fetch completed",
      updated_at: "just now",
      git_action: {},
    }),
    runProcessAction: vi.fn().mockResolvedValue({
      ok: true,
      status: "success",
      message: "UI Preview started",
      updated_at: "just now",
      service: data.fallbackProcesses.items[0],
    }),
    exportTelemetry: vi.fn().mockResolvedValue({
      version: "1.0",
      export: {
        created_at: "just now",
        telemetry: data.fallbackTelemetry,
      },
    }),
    fetchBraindrainLogs: vi.fn().mockResolvedValue(intelligenceFallbacks.logs),
    fetchPrimer: vi.fn().mockResolvedValue(intelligenceFallbacks.primer),
    fetchConfigPage: vi.fn().mockResolvedValue(intelligenceFallbacks.config),
    fetchAgents: vi.fn().mockResolvedValue(intelligenceFallbacks.agents),
    fetchSkills: vi.fn().mockResolvedValue(intelligenceFallbacks.skills),
    fetchPlans: vi.fn().mockResolvedValue(intelligenceFallbacks.plans),
    fetchTests: vi.fn().mockResolvedValue(intelligenceFallbacks.tests),
    intelligenceFallbacks,
    refreshWorkspace: vi.fn().mockResolvedValue({ ok: true }),
  };
});

function renderWorkspace() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <KeyboardProvider>
          <MemoryRouter initialEntries={["/"]}>
            <DashboardWorkspace />
          </MemoryRouter>
        </KeyboardProvider>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

describe("DashboardWorkspace", () => {
  it("keeps a shared command shell with desktop rail and compact tab strip", async () => {
    const user = userEvent.setup();
    renderWorkspace();

    expect(screen.getByLabelText(/primary command rail/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/primary dashboard tabs/i)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /overview/i })).toBeInTheDocument();

    await user.click(screen.getAllByRole("button", { name: /commands approved command presets/i })[0]);
    expect(screen.getByRole("heading", { name: /approved command presets/i })).toBeInTheDocument();
    expect(screen.getByRole("complementary", { name: /operational side panel/i })).toBeInTheDocument();

    await user.click(screen.getAllByRole("button", { name: /git branch drift and guarded sync/i })[0]);
    expect(await screen.findByText(/only guarded sync operations/i)).toBeInTheDocument();
  });
});
