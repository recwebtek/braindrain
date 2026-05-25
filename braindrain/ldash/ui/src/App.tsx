import { Route, Routes } from "react-router-dom";
import { AuthGate } from "@/components/AuthGate";
import { DashboardWorkspaceWithProviders } from "@/components/DashboardWorkspace";

export function App() {
  return (
    <AuthGate>
      <Routes>
        <Route path="*" element={<DashboardWorkspaceWithProviders />} />
      </Routes>
    </AuthGate>
  );
}
