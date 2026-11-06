import { useEffect, useState, useSyncExternalStore, type ReactNode } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import {
  LayoutDashboard,
  FolderSearch,
  Search,
  Users,
  Images,
  Phone,
  AtSign,
  UserSearch,
  Globe,
  Share2,
  Map,
  Clock,
  Zap,
  Activity,
  Database,
  Radar,
  Contact,
  Smartphone,
  Video,
  LogOut,
  MessageSquare,
  ShieldCheck,
  AudioLines,
} from "lucide-react";

import { StatusIndicator } from "@/components/StatusIndicator";
import { PairMobile } from "@/components/PairMobile";
import { PowerControl } from "@/components/PowerControl";
import { useAuth } from "@/lib/auth";
import { useActiveRuns } from "@/lib/kaiWork";
import { liveConversion } from "@/lib/liveConversion";

const BASE_TITLE = document.title;

const NAV: { icon: typeof Search; label: string; to?: string }[] = [
  { icon: LayoutDashboard, label: "Dashboard", to: "/" },
  { icon: MessageSquare, label: "KAI Chat", to: "/chat" },
  { icon: ShieldCheck, label: "Security", to: "/security" },
  { icon: AudioLines, label: "Voice Intelligence", to: "/voice" },
  { icon: Search, label: "Search", to: "/search" },
  { icon: FolderSearch, label: "Investigations", to: "/investigations" },
  { icon: Users, label: "Faces", to: "/face" },
  { icon: Video, label: "Live Camera", to: "/face/live" },
  { icon: Images, label: "Available Faces", to: "/faces" },
  { icon: Phone, label: "Phones", to: "/phone" },
  { icon: AtSign, label: "Emails", to: "/email" },
  { icon: UserSearch, label: "Usernames", to: "/username" },
  { icon: Contact, label: "Contacts", to: "/contacts" },
  { icon: Globe, label: "Domains" },
  { icon: Database, label: "Sources", to: "/sources" },
  { icon: Radar, label: "Discover", to: "/discover" },
  { icon: Share2, label: "Graph", to: "/graph" },
  { icon: Map, label: "Map", to: "/map" },
  { icon: Clock, label: "Timeline", to: "/timeline" },
  { icon: Zap, label: "Power Up", to: "/powerup" },
  { icon: Activity, label: "System", to: "/system" },
];

export function AppShell({ children }: { children: ReactNode }) {
  const { operator, logout } = useAuth();
  const [pairOpen, setPairOpen] = useState(false);
  const runs = useActiveRuns();
  const navigate = useNavigate();
  // Selecting primitives: level meters update the snapshot many times a second.
  const liveState = useSyncExternalStore(liveConversion.subscribe, () => liveConversion.getSnapshot().state);
  const liveDelayed = useSyncExternalStore(liveConversion.subscribe, () => liveConversion.getSnapshot().delayed);
  const liveNear = useSyncExternalStore(liveConversion.subscribe, () => liveConversion.getSnapshot().nearLive);
  const voiceLive = liveState === "live" || liveState === "starting" || liveState === "reconnecting";
  const voiceLabel = liveState === "starting" ? "Voice conversion starting"
    : liveState === "reconnecting" ? "Voice conversion reconnecting"
    : liveDelayed ? "Voice conversion delayed"
    : liveNear ? "Voice conversion on (seconds behind)" : "Voice conversion live";

  // Visible even from another browser tab: "⏳ KAI working…" in the tab title.
  useEffect(() => {
    document.title = voiceLive ? `🔴 Voice conversion · ${BASE_TITLE}`
      : runs.length ? `⏳ KAI working… · ${BASE_TITLE}` : BASE_TITLE;
    return () => { document.title = BASE_TITLE; };
  }, [runs.length, voiceLive]);

  return (
    <div className="flex min-h-screen bg-base text-ink">
      {pairOpen && <PairMobile onClose={() => setPairOpen(false)} />}
      {/* Sidebar */}
      <aside className="hidden w-56 shrink-0 flex-col border-r border-line bg-panel-2 md:flex">
        <div className="hud-scanlines border-b px-5 py-4" style={{ borderColor: "var(--kai-hud-dim)" }}>
          <div className="hud-mono hud-glow text-lg font-semibold tracking-[0.2em]" style={{ color: "var(--kai-hud)" }}>KAI</div>
          <div className="kai-metadata mt-0.5">Knowledge • Analysis • Intelligence</div>
        </div>
        <nav className="flex-1 space-y-0.5 p-3">
          {NAV.map(({ icon: Icon, label, to }) =>
            to ? (
              <NavLink
                key={label}
                to={to}
                end={to === "/"}
                className={({ isActive }) =>
                  `flex items-center gap-3 border-l-2 px-3 py-2 hud-mono text-[13px] transition-colors ${
                    isActive ? "border-current bg-panel" : "border-transparent text-muted hover:bg-panel hover:text-ink"
                  }`
                }
                style={({ isActive }) => (isActive ? { color: "var(--kai-hud)" } : undefined)}
              >
                <Icon size={16} />
                {label}
              </NavLink>
            ) : (
              <div
                key={label}
                title="Available in a later phase"
                className="flex cursor-default items-center gap-3 border-l-2 border-transparent px-3 py-2 hud-mono text-[13px] text-muted/60"
              >
                <Icon size={16} />
                {label}
              </div>
            ),
          )}
        </nav>
        {!(window as any).kaiDesktop && (
        <div className="border-t border-line p-3">
          <button
            onClick={() => { void liveConversion.stop(); logout(); }}
            className="flex w-full items-center gap-2 px-3 py-2 hud-mono text-[13px] text-muted hover:bg-panel hover:text-ink"
          >
            <LogOut size={16} /> Sign out
          </button>
        </div>
        )}
      </aside>

      {/* Main */}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between gap-4 border-b border-line bg-panel-2 px-4 py-3 sm:px-6">
          <div className="min-w-0 truncate kai-metadata flex items-center gap-2">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full" style={{ background: "var(--kai-hud)" }} />
            <span style={{ color: "var(--kai-hud)" }}>OPERATOR</span> / {operator?.email ?? "—"}
          </div>
          <div className="flex items-center gap-3">
            {runs.length > 0 && (
              <button
                onClick={() => navigate(`/chat?c=${runs[0].conversation_id}`)}
                title="KAI is working in the background — click to open"
                className="flex items-center gap-2 rounded border px-2 py-1 text-xs hud-mono"
                style={{ borderColor: "var(--kai-hud)", color: "var(--kai-hud)" }}
              >
                <span className="h-2 w-2 animate-pulse rounded-full" style={{ background: "var(--kai-hud)" }} />
                KAI working · {runs[0].activity}{runs.length > 1 ? ` (+${runs.length - 1})` : ""} · {runs[0].seconds}s
              </button>
            )}
            {voiceLive && (
              <button
                onClick={() => navigate("/voice?tab=live")}
                title="Your microphone is being converted. Click to open."
                className="flex items-center gap-2 rounded border px-2 py-1 text-xs hud-mono"
                style={{ borderColor: "var(--kai-accent)", color: "var(--kai-accent)" }}
              >
                <span className="h-2 w-2 animate-pulse rounded-full" style={{ background: "var(--kai-accent)" }} />
                {voiceLabel}
              </button>
            )}
            <button
              onClick={() => setPairOpen(true)}
              title="Pair mobile device (QR login)"
              className="flex items-center gap-1 rounded border border-line px-2 py-1 text-xs hover:bg-panel"
            >
              <Smartphone size={14} /> Pair mobile
            </button>
            <PowerControl />
            <StatusIndicator />
          </div>
        </header>
        <nav className="flex gap-1 overflow-x-auto border-b border-line bg-panel-2 px-3 py-2 md:hidden">
          {NAV.filter(({ to }) => to).map(({ icon: Icon, label, to }) => (
            <NavLink
              key={label}
              to={to!}
              end={to === "/"}
              className={({ isActive }) => `flex shrink-0 items-center gap-2 border-b-2 px-3 py-2 hud-mono text-xs ${isActive ? "bg-panel" : "border-transparent text-muted"}`}
              style={({ isActive }) => (isActive ? { color: "var(--kai-hud)", borderColor: "var(--kai-hud)" } : undefined)}
            >
              <Icon size={14} /> {label}
            </NavLink>
          ))}
        </nav>
        <main className="min-w-0 flex-1 overflow-auto p-4 sm:p-6">{children}</main>
      </div>
    </div>
  );
}
