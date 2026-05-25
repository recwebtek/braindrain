import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HomeShell } from "@/components/HomeShell";
import { fallbackOverview, fallbackTelemetry } from "@/data";

describe("HomeShell", () => {
  it("renders the overview as an operational module without the old footer bar", async () => {
    const user = userEvent.setup();
    const onOpenTab = vi.fn();

    render(<HomeShell overview={fallbackOverview} telemetry={fallbackTelemetry} onOpenTab={onOpenTab} />);

    expect(screen.getByRole("main", { name: /overview operations/i })).toBeInTheDocument();
    expect(screen.getByRole("complementary", { name: /overview signal rail/i })).toBeInTheDocument();
    expect(screen.getByLabelText(/workspace fact strip/i)).toBeInTheDocument();
    expect(screen.queryByRole("contentinfo")).not.toBeInTheDocument();

    const chip = screen.getAllByTestId("fact-chip")[0];
    expect(chip).toHaveClass("whitespace-nowrap");

    await user.click(screen.getByRole("button", { name: /open commands run approved workspace commands/i }));
    expect(onOpenTab).toHaveBeenCalledWith("commands");
  });
});
