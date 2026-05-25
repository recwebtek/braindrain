import { Route, Routes } from "react-router-dom";
import { AuthGate } from "@/components/AuthGate";
import { DashboardWorkspace } from "@/components/DashboardWorkspace";

export function App() {
  return (
    <AuthGate>
      <Routes>
        <Route path="*" element={<DashboardWorkspace />} />
      </Routes>
    </AuthGate>
  );
}
