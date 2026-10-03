import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";
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
  LogOut,
} from "lucide-react";

import { StatusIndicator } from "@/components/StatusIndicator";
import { useAuth } from "@/lib/auth";

const NAV: { icon: typeof Search; label: string; to?: string }[] = [
  { icon: LayoutDashboard, label: "Dashboard", to: "/" },
  { icon: Search, label: "Search", to: "/search" },
  { icon: FolderSearch, label: "Investigations", to: "/investigations" },
  { icon: Users, label: "Faces", to: "/face" },
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

  return (
    <div className="flex min-h-screen bg-base text-ink">
      {/* Sidebar */}
      <aside className="hidden w-56 shrink-0 flex-col border-r border-line bg-panel-2 md:flex">
        <div className="border-b border-line px-5 py-4">
          <div className="text-lg font-semibold tracking-wide">KAI</div>
          <div className="kai-metadata mt-0.5">Knowledge • Analysis • Intelligence</div>
        </div>
        <nav className="flex-1 space-y-1 p-3">
          {NAV.map(({ icon: Icon, label, to }) =>
            to ? (
              <NavLink
                key={label}
                to={to}
                end={to === "/"}
                className={({ isActive }) =>
                  `flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors ${
                    isActive ? "bg-panel text-ink" : "text-muted hover:bg-panel hover:text-ink"
                  }`
                }
              >
                <Icon size={16} />
                {label}
              </NavLink>
            ) : (
              <div
                key={label}
                title="Available in a later phase"
                className="flex cursor-default items-center gap-3 rounded-md px-3 py-2 text-sm text-muted/60"
              >
                <Icon size={16} />
                {label}
              </div>
            ),
          )}
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
        <header className="flex items-center justify-between gap-4 border-b border-line bg-panel-2 px-4 py-3 sm:px-6">
          <div className="min-w-0 truncate kai-metadata">OPERATOR / {operator?.email ?? "—"}</div>
          <StatusIndicator />
        </header>
        <nav className="flex gap-1 overflow-x-auto border-b border-line bg-panel-2 px-3 py-2 md:hidden">
          {NAV.filter(({ to }) => to).map(({ icon: Icon, label, to }) => (
            <NavLink
              key={label}
              to={to!}
              end={to === "/"}
              className={({ isActive }) => `flex shrink-0 items-center gap-2 px-3 py-2 text-xs ${isActive ? "bg-panel text-ink" : "text-muted"}`}
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
