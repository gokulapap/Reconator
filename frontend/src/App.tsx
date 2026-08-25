import { Navigate, Route, Routes } from "react-router-dom";

import { Layout } from "@/components/Layout";
import { ThemeProvider } from "@/components/ThemeProvider";
import { Toaster } from "@/components/ui/toaster";
import { Dashboard } from "@/pages/Dashboard";
import { Targets } from "@/pages/Targets";
import { TargetDetail } from "@/pages/TargetDetail";
import { Modules } from "@/pages/Modules";
import { Settings } from "@/pages/Settings";

export default function App() {
  return (
    <ThemeProvider>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Dashboard />} />
          <Route path="targets" element={<Targets />} />
          <Route path="targets/:id" element={<TargetDetail />} />
          <Route path="modules" element={<Modules />} />
          <Route path="settings" element={<Settings />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
      <Toaster />
    </ThemeProvider>
  );
}
