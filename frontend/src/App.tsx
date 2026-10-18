import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "@/components/AppShell";
import { TopProgress } from "@/components/TopProgress";
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
import { FaceLive } from "@/pages/FaceLive";
import { FaceIndex } from "@/pages/FaceIndex";
import { Sources } from "@/pages/Sources";
import { Discover } from "@/pages/Discover";
import { Contacts } from "@/pages/Contacts";
import { Investigate } from "@/pages/Investigate";
import { Queue } from "@/pages/Queue";
import { PowerUp } from "@/pages/PowerUp";
import { MapView } from "@/pages/MapView";
import { Timeline } from "@/pages/Timeline";
import { System } from "@/pages/System";
import { Chat } from "@/pages/Chat";
import { Security } from "@/pages/Security";
import { Home } from "@/pages/Home";

export default function App() {
  const { operator, loading } = useAuth();

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-base">
        <span className="kai-metadata">INITIALIZING…</span>
      </div>
    );
  }

  return (
    <BrowserRouter>
      <TopProgress />
      {!operator ? (
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/login" element={<Login />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      ) : (
        <AppShell>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/chat" element={<Chat />} />
            <Route path="/security" element={<Security />} />
            <Route path="/search" element={<Search />} />
            <Route path="/phone" element={<Phone />} />
            <Route path="/email" element={<Email />} />
            <Route path="/username" element={<Username />} />
            <Route path="/face" element={<Face />} />
            <Route path="/face/live" element={<FaceLive />} />
            <Route path="/faces" element={<FaceIndex />} />
            <Route path="/sources" element={<Sources />} />
            <Route path="/discover" element={<Discover />} />
            <Route path="/contacts" element={<Contacts />} />
            <Route path="/investigate" element={<Investigate />} />
            <Route path="/queue" element={<Queue />} />
            <Route path="/graph" element={<Graph />} />
            <Route path="/map" element={<MapView />} />
            <Route path="/timeline" element={<Timeline />} />
            <Route path="/powerup" element={<PowerUp />} />
            <Route path="/system" element={<System />} />
            <Route path="/investigations" element={<Investigations />} />
            <Route path="/investigations/:id" element={<Investigation />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </AppShell>
      )}
    </BrowserRouter>
  );
}
