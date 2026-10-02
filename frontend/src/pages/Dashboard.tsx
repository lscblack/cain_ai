import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { Users, Phone, AtSign, Database, Search, Globe, Images, Map } from "lucide-react";

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

  useEffect(() => {
    const load = () => {
      api.get<Stats>("/system/stats").then(setStats).catch(() => setStats(null));
      investigationsApi.list().then((c) => setCases(c.slice(0, 6))).catch(() => setCases([]));
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

  return (
    <>
      <form onSubmit={onSearch} className="mb-6 flex items-center gap-2 rounded-lg border border-line bg-panel px-3 py-3 sm:px-4">
        <Search size={16} className="text-muted" />
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search phone / email / username / domain / url"
          className="w-full bg-transparent text-sm outline-none placeholder:text-muted"
        />
      </form>

      <div className="mb-6 grid grid-cols-2 gap-3 sm:gap-4 md:grid-cols-4">
        {tiles.map(({ icon: Icon, label, value, to }, i) => (
          <motion.div key={label} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }}>
            <Link to={to} className="block rounded-lg border border-line bg-panel p-4 hover:border-muted">
              <div className="flex items-center justify-between">
                <span className="kai-metadata uppercase">{label}</span>
                <Icon size={15} className="text-muted" />
              </div>
              <div className="mt-2 font-mono text-xl sm:text-2xl">{value.toLocaleString()}</div>
            </Link>
          </motion.div>
        ))}
      </div>

      {/* Map shortcut */}
      <Link to="/map" className="mb-6 flex min-h-32 items-center justify-center rounded-lg border border-line bg-panel-2 p-5 text-center hover:border-muted sm:h-40">
        <span className="flex flex-wrap items-center justify-center gap-2 kai-metadata">
          <Map size={16} /> OPEN LIVE INTELLIGENCE MAP — aircraft · vessels · fires · webcams
        </span>
      </Link>

      <div className="grid gap-4 md:grid-cols-2">
        <div className="rounded-lg border border-line bg-panel p-4">
          <div className="kai-metadata mb-3 flex items-center justify-between uppercase">
            Recent Investigations
            <Link to="/investigations" className="hover:text-ink">view all →</Link>
          </div>
          {cases.length === 0 ? (
            <div className="text-sm text-muted">No investigations yet.</div>
          ) : (
            <div className="space-y-2">
              {cases.map((ci) => (
                <Link key={ci.id} to={`/investigations/${ci.id}`} className="flex min-w-0 flex-col gap-1 rounded-md border border-line px-3 py-2 hover:border-muted sm:flex-row sm:items-center sm:justify-between">
                  <span className="truncate text-sm">{ci.name}</span>
                  <span className="kai-metadata shrink-0">{ci.code} · ent {ci.entity_count} · evd {ci.evidence_count}</span>
                </Link>
              ))}
            </div>
          )}
        </div>

        <div className="rounded-lg border border-line bg-panel p-4">
          <div className="kai-metadata mb-3 uppercase">Index Activity</div>
          <div className="grid grid-cols-2 gap-2 font-mono text-sm">
            <Stat label="Faces" value={c.faces} icon={<Users size={13} />} />
            <Stat label="Images" value={c.images} icon={<Images size={13} />} />
            <Stat label="Pages" value={c.pages} icon={<Globe size={13} />} />
            <Stat label="Sources" value={c.sources} icon={<Database size={13} />} />
            <Stat label="Entities" value={c.entities} />
            <Stat label="Evidence" value={c.evidence} />
          </div>
          {stats && (
            <div className="kai-metadata mt-3 border-t border-line pt-2">
              face engine {stats.services.face_engine ? "online" : "offline"} · postgres{" "}
              {stats.services.postgres ? "up" : "down"} · redis {stats.services.redis ? "up" : "down"}
            </div>
          )}
        </div>
      </div>
    </>
  );
}

function Stat({ label, value, icon }: { label: string; value?: number; icon?: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between rounded-md border border-line px-3 py-2">
      <span className="kai-metadata flex items-center gap-1 uppercase">{icon} {label}</span>
      <span>{(value ?? 0).toLocaleString()}</span>
    </div>
  );
}
