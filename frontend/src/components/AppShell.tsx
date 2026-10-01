import type { ReactNode } from "react";
import {
  LayoutDashboard,
  Search,
  Users,
  Phone,
  AtSign,
  Globe,
  Share2,
  Map,
  Clock,
  Zap,
  LogOut,
} from "lucide-react";

import { StatusIndicator } from "@/components/StatusIndicator";
import { useAuth } from "@/lib/auth";

const NAV = [
  { icon: LayoutDashboard, label: "Dashboard", active: true },
  { icon: Search, label: "Search" },
  { icon: Users, label: "Faces" },
  { icon: Phone, label: "Phones" },
  { icon: AtSign, label: "Emails" },
  { icon: Globe, label: "Domains" },
  { icon: Share2, label: "Graph" },
  { icon: Map, label: "Map" },
  { icon: Clock, label: "Timeline" },
  { icon: Zap, label: "Power Up" },
];

export function AppShell({ children }: { children: ReactNode }) {
  const { operator, logout } = useAuth();

  return (
    <div className="flex min-h-screen bg-base text-ink">
      {/* Sidebar */}
      <aside className="hidden w-56 shrink-0 flex-col border-r border-line bg-panel-2 md:flex">
        <div className="border-b border-line px-5 py-4">
          <div className="text-lg font-semibold tracking-wide">KAI</div>
          <div className="kai-metadata mt-0.5">Knowledge • Analysis • Intelligence</div>
        </div>
        <nav className="flex-1 space-y-1 p-3">
          {NAV.map(({ icon: Icon, label, active }) => (
            <div
              key={label}
              className={`flex items-center gap-3 rounded-md px-3 py-2 text-sm ${
                active ? "bg-panel text-ink" : "text-muted hover:bg-panel hover:text-ink"
              } cursor-default transition-colors`}
            >
              <Icon size={16} />
              {label}
            </div>
          ))}
        </nav>
        <div className="border-t border-line p-3">
          <button
            onClick={logout}
            className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-sm text-muted hover:bg-panel hover:text-ink"
          >
            <LogOut size={16} /> Sign out
          </button>
        </div>
      </aside>

      {/* Main */}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-line bg-panel-2 px-6 py-3">
          <div className="kai-metadata">OPERATOR / {operator?.email ?? "—"}</div>
          <StatusIndicator />
        </header>
        <main className="flex-1 overflow-auto p-6">{children}</main>
      </div>
    </div>
  );
}
