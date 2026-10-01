import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "@/components/AppShell";
import { useAuth } from "@/lib/auth";
import { Login } from "@/pages/Login";
import { Dashboard } from "@/pages/Dashboard";
import { Investigations } from "@/pages/Investigations";
import { Investigation } from "@/pages/Investigation";
import { Search } from "@/pages/Search";
import { Phone } from "@/pages/Phone";

export default function App() {
  const { operator, loading } = useAuth();

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-base">
        <span className="kai-metadata">INITIALIZING…</span>
      </div>
    );
  }

  if (!operator) return <Login />;

  return (
    <BrowserRouter>
      <AppShell>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/search" element={<Search />} />
          <Route path="/phone" element={<Phone />} />
          <Route path="/investigations" element={<Investigations />} />
          <Route path="/investigations/:id" element={<Investigation />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AppShell>
    </BrowserRouter>
  );
}
