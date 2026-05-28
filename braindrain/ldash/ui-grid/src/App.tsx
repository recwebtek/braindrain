import { AuthGate } from "@/components/AuthGate";
import { GridCockpit } from "@/components/GridCockpit";

export function App() {
  return (
    <AuthGate>
      <GridCockpit />
    </AuthGate>
  );
}
