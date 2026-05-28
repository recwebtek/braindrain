import { Route, Routes } from "react-router-dom";
import { AuthGate } from "@/components/AuthGate";
import { NexusDashboard } from "@/components/NexusDashboard";

export function App() {
  return (
    <AuthGate>
      <Routes>
        <Route path="*" element={<NexusDashboard />} />
      </Routes>
    </AuthGate>
  );
}
