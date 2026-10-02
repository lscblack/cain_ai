import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import {
  Users, Phone, AtSign, Database, Search, Globe, Images, Map, ArrowUpRight,
} from "lucide-react";

import { api } from "@/lib/api";
import { investigationsApi } from "@/lib/investigations";
import type { InvestigationDetail } from "@/types";

interface Stats {
  services: Record<string, boolean>;
  counts: Record<string, number>;
}

export function Dashboard() {
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  const [stats, setStats] = useState<Stats | null>(null);
  const [cases, setCases] = useState<InvestigationDetail[]>([]);
  const [queued, setQueued] = useState<number | null>(null);

  async function clearQueue() {
    if (!confirm("Clear the crawl queue and reset stuck sources?")) return;
    const r = await api.post<{ cleared: number }>("/sources/queue/clear").catch(() => null);
    if (r) { alert(`Cleared ${r.cleared} queued crawl job(s).`); loadQueue(); }
  }
  function loadQueue() {
    api.get<{ queued: number }>("/sources/queue").then((r) => setQueued(r.queued)).catch(() => setQueued(null));
  }

  useEffect(() => {
    const load = () => {
      api.get<Stats>("/system/stats").then(setStats).catch(() => setStats(null));
      investigationsApi.list().then((c) => setCases(c.slice(0, 6))).catch(() => setCases([]));
      loadQueue();
    };
    load();
    const id = setInterval(load, 8000);
    return () => clearInterval(id);
  }, []);

  function onSearch(e: FormEvent) {
    e.preventDefault();
    if (q.trim()) navigate(`/search?q=${encodeURIComponent(q.trim())}`);
  }

  const c = stats?.counts ?? {};
  const tiles = [
    { icon: Users, label: "Faces", value: c.faces ?? 0, to: "/faces" },
    { icon: Phone, label: "Phones", value: c.phones ?? 0, to: "/phone" },
    { icon: AtSign, label: "Emails", value: c.emails ?? 0, to: "/email" },
    { icon: Database, label: "Sources", value: c.sources ?? 0, to: "/sources" },
  ];
  const svc = stats?.services ?? {};

  return (
    <div className="relative">
      <div className="home-grid pointer-events-none absolute -inset-6 -z-10 opacity-30" aria-hidden="true" />

      {/* console header */}
      <div className="mb-5 flex items-center gap-2 font-mono text-xs tracking-[0.25em] text-accent">
        <span className="h-2 w-2 animate-pulse rounded-full bg-accent" /> OPERATOR CONSOLE / 01
      </div>

      {/* universal search */}
      <form onSubmit={onSearch} className="mb-6 flex items-center gap-2 border border-line bg-panel/95 px-3 py-3 transition focus-within:border-accent sm:px-4">
        <Search size={16} className="text-accent" />
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="SEARCH PHONE / EMAIL / USERNAME / DOMAIN / URL"
          className="w-full bg-transparent font-mono text-sm outline-none placeholder:tracking-wider placeholder:text-muted"
        />
      </form>

      {/* stat tiles */}
      <div className="mb-6 grid grid-cols-2 gap-px border border-line bg-line/40 md:grid-cols-4">
        {tiles.map(({ icon: Icon, label, value, to }, i) => (
          <motion.div key={label} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }}>
            <Link to={to} className="group flex h-full flex-col justify-between bg-panel p-4 transition hover:bg-panel-2">
              <div className="flex items-center justify-between">
                <span className="kai-metadata uppercase tracking-wider">{label}</span>
                <Icon size={15} className="text-muted transition group-hover:text-accent" />
              </div>
              <div className="mt-3 font-mono text-2xl font-semibold sm:text-3xl">{value.toLocaleString()}</div>
            </Link>
          </motion.div>
        ))}
      </div>

      {/* crawl queue control */}
      <div className="mb-6 flex flex-wrap items-center gap-3 border border-line bg-panel/95 px-4 py-3 font-mono text-xs">
        <span className="kai-metadata uppercase tracking-wider">Crawl queue</span>
        <span className="text-lg font-semibold" style={{ color: queued ? "var(--kai-warn)" : "var(--kai-verified)" }}>
          {queued ?? "—"}
        </span>
        <span className="text-muted">job(s) pending</span>
        <div className="ml-auto flex gap-2">
          <Link to="/sources" className="border border-line px-3 py-1.5 uppercase tracking-wider text-muted transition hover:border-accent hover:text-ink">Manage sources</Link>
          <Link to="/discover" className="border px-3 py-1.5 uppercase tracking-wider transition"
            style={{ borderColor: "var(--kai-accent)", color: "var(--kai-accent)" }}>Discover new sources</Link>
          <button onClick={clearQueue} disabled={!queued} className="border border-line px-3 py-1.5 uppercase tracking-wider text-muted transition hover:border-accent hover:text-ink disabled:opacity-40">Clear queue</button>
        </div>
      </div>

      {/* map shortcut */}
      <Link to="/map" className="group relative mb-6 flex min-h-32 items-center justify-center overflow-hidden border border-line bg-panel-2 p-5 text-center transition hover:border-accent sm:h-40">
        <div className="home-grid pointer-events-none absolute inset-0 opacity-30" aria-hidden="true" />
        <span className="relative flex flex-wrap items-center justify-center gap-2 font-mono text-xs uppercase tracking-wider text-muted group-hover:text-ink">
          <Map size={16} className="text-accent" /> Open live intelligence map
          <span className="text-muted">— aircraft · vessels · fires · webcams</span>
          <ArrowUpRight size={14} className="text-accent" />
        </span>
      </Link>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* recent investigations */}
        <div className="border border-line bg-panel/95 p-4">
          <div className="mb-3 flex items-center justify-between border-b border-line pb-2 font-mono text-[11px] uppercase tracking-[0.2em] text-muted">
            <span>Recent Investigations</span>
            <Link to="/investigations" className="text-accent hover:brightness-125">view all →</Link>
          </div>
          {cases.length === 0 ? (
            <div className="py-6 text-center font-mono text-xs uppercase tracking-wider text-muted">No investigations yet</div>
          ) : (
            <div className="space-y-2">
              {cases.map((ci) => (
                <Link key={ci.id} to={`/investigations/${ci.id}`} className="flex min-w-0 flex-col gap-1 border border-line px-3 py-2 transition hover:border-accent sm:flex-row sm:items-center sm:justify-between">
                  <span className="truncate text-sm">{ci.name}</span>
                  <span className="kai-metadata shrink-0">{ci.code} · ent {ci.entity_count} · evd {ci.evidence_count}</span>
                </Link>
              ))}
            </div>
          )}
        </div>

        {/* index activity */}
        <div className="border border-line bg-panel/95 p-4">
          <div className="mb-3 border-b border-line pb-2 font-mono text-[11px] uppercase tracking-[0.2em] text-muted">Index Activity</div>
          <div className="grid grid-cols-2 gap-px bg-line/40">
            <Stat label="Faces" value={c.faces} icon={<Users size={13} />} />
            <Stat label="Images" value={c.images} icon={<Images size={13} />} />
            <Stat label="Pages" value={c.pages} icon={<Globe size={13} />} />
            <Stat label="Sources" value={c.sources} icon={<Database size={13} />} />
            <Stat label="Entities" value={c.entities} />
            <Stat label="Evidence" value={c.evidence} />
          </div>
          <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 border-t border-line pt-3 font-mono text-[11px] uppercase tracking-wider">
            <Svc label="face engine" ok={svc.face_engine} />
            <Svc label="postgres" ok={svc.postgres} />
            <Svc label="redis" ok={svc.redis} />
          </div>
        </div>
      </div>
    </div>
  );
}

function Stat({ label, value, icon }: { label: string; value?: number; icon?: ReactNode }) {
  return (
    <div className="flex items-center justify-between bg-panel px-3 py-2 font-mono text-sm">
      <span className="kai-metadata flex items-center gap-1.5 uppercase">{icon} {label}</span>
      <span className="font-semibold">{(value ?? 0).toLocaleString()}</span>
    </div>
  );
}

function Svc({ label, ok }: { label: string; ok?: boolean }) {
  const color = ok ? "var(--kai-verified)" : "var(--kai-accent)";
  return (
    <span className="flex items-center gap-1.5" style={{ color }}>
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: color }} /> {label} {ok ? "up" : "down"}
    </span>
  );
}
