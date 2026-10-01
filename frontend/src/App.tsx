import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "@/components/AppShell";
import { useAuth } from "@/lib/auth";
import { Login } from "@/pages/Login";
import { Dashboard } from "@/pages/Dashboard";
import { Investigations } from "@/pages/Investigations";
import { Investigation } from "@/pages/Investigation";
import { Search } from "@/pages/Search";
import { Phone } from "@/pages/Phone";
import { Email } from "@/pages/Email";
import { Username } from "@/pages/Username";
import { Graph } from "@/pages/Graph";
import { Face } from "@/pages/Face";
import { Sources } from "@/pages/Sources";
import { PowerUp } from "@/pages/PowerUp";
import { MapView } from "@/pages/MapView";
import { Timeline } from "@/pages/Timeline";

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
          <Route path="/email" element={<Email />} />
          <Route path="/username" element={<Username />} />
          <Route path="/face" element={<Face />} />
          <Route path="/sources" element={<Sources />} />
          <Route path="/graph" element={<Graph />} />
          <Route path="/map" element={<MapView />} />
          <Route path="/timeline" element={<Timeline />} />
          <Route path="/powerup" element={<PowerUp />} />
          <Route path="/investigations" element={<Investigations />} />
          <Route path="/investigations/:id" element={<Investigation />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AppShell>
    </BrowserRouter>
  );
}
