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
interface QueueDetail {
  queued: number;
  discovery_queued: number;
  crawling: { id: string; domain: string; since: string | null }[];
  queued_next: { id: string; domain: string }[];
}

export function Dashboard() {
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  const [stats, setStats] = useState<Stats | null>(null);
  const [cases, setCases] = useState<InvestigationDetail[]>([]);
  const [queued, setQueued] = useState<number | null>(null);
  const [queueDetail, setQueueDetail] = useState<QueueDetail | null>(null);
  const [showQueue, setShowQueue] = useState(false);

  async function clearQueue() {
    if (!confirm("Clear the crawl queue and reset stuck sources?")) return;
    const r = await api.post<{ cleared: number }>("/sources/queue/clear").catch(() => null);
    if (r) { alert(`Cleared ${r.cleared} queued crawl job(s).`); loadQueue(); }
  }
  function loadQueue() {
    api.get<QueueDetail>("/sources/queue").then((r) => { setQueued(r.queued); setQueueDetail(r); }).catch(() => setQueued(null));
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
      <div className="mb-5 flex items-center gap-2 hud-mono hud-glow text-xs tracking-[0.25em]" style={{ color: "var(--kai-hud)" }}>
        <span className="h-2 w-2 animate-pulse rounded-full" style={{ background: "var(--kai-hud)" }} /> ◢ OPERATOR CONSOLE / 01
      </div>

      {/* universal search */}
      <form onSubmit={onSearch} className="hud-panel hud-frame mb-6 flex items-center gap-2 px-3 py-3 transition focus-within:border-[color:var(--kai-hud)] sm:px-4">
        <Search size={16} style={{ color: "var(--kai-hud)" }} />
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="SEARCH PHONE / EMAIL / USERNAME / DOMAIN / URL"
          className="w-full bg-transparent font-mono text-sm outline-none placeholder:tracking-wider placeholder:text-muted"
        />
      </form>

      {/* stat tiles */}
      <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-4">
        {tiles.map(({ icon: Icon, label, value, to }, i) => (
          <motion.div key={label} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }}>
            <Link to={to} className="hud-panel hud-frame group flex h-full flex-col justify-between p-4 transition hover:brightness-125">
              <div className="flex items-center justify-between">
                <span className="hud-mono uppercase tracking-wider text-xs" style={{ color: "var(--kai-hud)" }}>{label}</span>
                <Icon size={15} className="text-muted transition group-hover:text-ink" />
              </div>
              <div className="mt-3 hud-mono hud-glow text-2xl font-semibold sm:text-3xl" style={{ color: "var(--kai-hud)" }}>{value.toLocaleString()}</div>
            </Link>
          </motion.div>
        ))}
      </div>

      {/* crawl queue control */}
      <div className="hud-panel hud-frame mb-6 font-mono text-xs">
        <div className="flex flex-wrap items-center gap-3 px-4 py-3">
          <span className="hud-mono uppercase tracking-wider" style={{ color: "var(--kai-hud)" }}>◢ Crawl queue</span>
          <span className="text-lg font-semibold" style={{ color: queued ? "var(--kai-warn)" : "var(--kai-verified)" }}>
            {queued ?? "—"}
          </span>
          <span className="text-muted">pending{(queueDetail?.crawling.length ?? 0) > 0 ? ` · ${queueDetail!.crawling.length} crawling` : ""}{(queueDetail?.discovery_queued ?? 0) > 0 ? ` · ${queueDetail!.discovery_queued} discovery` : ""}</span>
          <button onClick={() => setShowQueue((v) => !v)} className="border border-line px-3 py-1.5 uppercase tracking-wider text-muted transition hover:border-[color:var(--kai-hud)] hover:text-ink">
            {showQueue ? "Hide queue" : "View queue"}
          </button>
          <div className="ml-auto flex gap-2">
            <Link to="/sources" className="border border-line px-3 py-1.5 uppercase tracking-wider text-muted transition hover:border-[color:var(--kai-hud)] hover:text-ink">Manage sources</Link>
            <Link to="/discover" className="border px-3 py-1.5 uppercase tracking-wider transition hover:brightness-125"
              style={{ borderColor: "var(--kai-hud-dim)", color: "var(--kai-hud)" }}>Discover new sources</Link>
            <Link to="/investigate" className="border px-3 py-1.5 uppercase tracking-wider transition hover:brightness-125"
              style={{ borderColor: "var(--kai-hud-dim)", color: "var(--kai-hud)" }}>Investigate names</Link>
            <button onClick={clearQueue} disabled={!queued} className="border border-line px-3 py-1.5 uppercase tracking-wider text-muted transition hover:border-[color:var(--kai-accent)] hover:text-ink disabled:opacity-40">Clear queue</button>
          </div>
        </div>
        {showQueue && (
          <div className="grid gap-4 border-t border-line p-4 sm:grid-cols-2">
            <div>
              <div className="kai-metadata mb-2 uppercase">Currently crawling ({queueDetail?.crawling.length ?? 0})</div>
              {(queueDetail?.crawling.length ?? 0) === 0 ? <div className="text-muted">— idle —</div> : (
                <div className="space-y-1">
                  {queueDetail!.crawling.map((s) => (
                    <div key={s.id} className="flex items-center gap-2 truncate">
                      <span className="h-1.5 w-1.5 shrink-0 animate-pulse rounded-full" style={{ background: "var(--kai-warn)" }} />
                      <span className="truncate text-ink">{s.domain}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
            <div>
              <div className="kai-metadata mb-2 uppercase">Next up ({queued ?? 0} queued, showing {queueDetail?.queued_next.length ?? 0})</div>
              {(queueDetail?.queued_next.length ?? 0) === 0 ? <div className="text-muted">— empty —</div> : (
                <div className="max-h-56 space-y-1 overflow-auto">
                  {queueDetail!.queued_next.map((s, i) => (
                    <div key={s.id + i} className="truncate text-muted">{i + 1}. {s.domain}</div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* map shortcut */}
      <Link to="/map" className="hud-panel hud-frame group relative mb-6 flex min-h-32 items-center justify-center overflow-hidden p-5 text-center transition hover:brightness-125 sm:h-40">
        <div className="home-grid pointer-events-none absolute inset-0 opacity-30" aria-hidden="true" />
        <span className="relative flex flex-wrap items-center justify-center gap-2 hud-mono text-xs uppercase tracking-wider text-muted group-hover:text-ink">
          <Map size={16} style={{ color: "var(--kai-hud)" }} /> Open live intelligence map
          <span className="text-muted">— aircraft · vessels · fires · webcams</span>
          <ArrowUpRight size={14} style={{ color: "var(--kai-hud)" }} />
        </span>
      </Link>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* recent investigations */}
        <div className="hud-panel hud-frame p-4">
          <div className="mb-3 flex items-center justify-between border-b border-line pb-2 hud-mono text-[11px] uppercase tracking-[0.2em]" style={{ color: "var(--kai-hud)" }}>
            <span>◢ Recent Investigations</span>
            <Link to="/investigations" className="hover:brightness-125" style={{ color: "var(--kai-hud)" }}>view all →</Link>
          </div>
          {cases.length === 0 ? (
            <div className="py-6 text-center hud-mono text-xs uppercase tracking-wider text-muted">No investigations yet</div>
          ) : (
            <div className="space-y-2">
              {cases.map((ci) => (
                <Link key={ci.id} to={`/investigations/${ci.id}`} className="flex min-w-0 flex-col gap-1 border border-line px-3 py-2 transition hover:border-[color:var(--kai-hud)] sm:flex-row sm:items-center sm:justify-between">
                  <span className="truncate text-sm">{ci.name}</span>
                  <span className="kai-metadata shrink-0">{ci.code} · ent {ci.entity_count} · evd {ci.evidence_count}</span>
                </Link>
              ))}
            </div>
          )}
        </div>

        {/* index activity */}
        <div className="hud-panel hud-frame p-4">
          <div className="mb-3 border-b border-line pb-2 hud-mono text-[11px] uppercase tracking-[0.2em]" style={{ color: "var(--kai-hud)" }}>◢ Index Activity</div>
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
