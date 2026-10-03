import { useEffect, useRef, useState } from "react";
import { Contact, Mail, Phone, AtSign, ExternalLink } from "lucide-react";

import { api } from "@/lib/api";

interface ContactRow {
  value: string;
  kind: string;
  pages: number;
  sample_url: string | null;
  sample_title: string | null;
}
interface Stats {
  pages: number;
  emails: number;
  phones: number;
  usernames: number;
}

const KINDS = [
  { key: "all", label: "All" },
  { key: "phone", label: "Phones" },
  { key: "email", label: "Emails" },
  { key: "username", label: "Usernames" },
];

function KindIcon({ kind }: { kind: string }) {
  if (kind.startsWith("email")) return <Mail size={13} className="text-muted" />;
  if (kind.startsWith("phone")) return <Phone size={13} className="text-verified" />;
  return <AtSign size={13} className="text-accent" />;
}

export function Contacts() {
  const [q, setQ] = useState("");
  const [kind, setKind] = useState("all");
  const [rows, setRows] = useState<ContactRow[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [busy, setBusy] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  async function loadStats() {
    try {
      setStats(await api.get<Stats>("/contacts/stats"));
    } catch {
      /* ignore */
    }
  }

  async function run(query: string, k: string) {
    setBusy(true);
    try {
      const r = await api.get<{ results: ContactRow[] }>(
        `/contacts/search?q=${encodeURIComponent(query)}&kind=${k}&limit=100`,
      );
      setRows(r.results);
    } catch {
      setRows([]);
    } finally {
      setBusy(false);
    }
  }

  // live: debounce as the operator types
  useEffect(() => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => run(q, kind), 220);
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, [q, kind]);

  useEffect(() => {
    loadStats();
  }, []);

  return (
    <div className="w-11/12 max-w-[1700px] mx-auto space-y-5">
      <header className="flex items-center gap-3">
        <Contact className="text-accent" size={22} />
        <div>
          <h1 className="text-xl font-semibold tracking-wide">Contacts</h1>
          <p className="kai-metadata">Live search over crawled phones · emails · usernames</p>
        </div>
      </header>

      {stats && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Stat label="Pages crawled" value={stats.pages} />
          <Stat label="Phones" value={stats.phones} accent />
          <Stat label="Emails" value={stats.emails} accent />
          <Stat label="Usernames" value={stats.usernames} accent />
        </div>
      )}

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <input
          autoFocus
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Type to search… +2507, @handle, name@site.com"
          className="min-h-11 flex-1 border border-line bg-panel-2 px-3 font-mono text-sm outline-none focus:border-accent"
        />
        <div className="flex gap-1">
          {KINDS.map((k) => (
            <button
              key={k.key}
              onClick={() => setKind(k.key)}
              className={`border px-3 py-2 text-xs uppercase tracking-wider transition ${
                kind === k.key ? "border-accent text-accent" : "border-line text-muted hover:text-ink"
              }`}
            >
              {k.label}
            </button>
          ))}
        </div>
      </div>

      <div className="border border-line bg-panel-2">
        <div className="flex items-center justify-between border-b border-line px-3 py-2 kai-metadata">
          <span>{busy ? "searching…" : `${rows.length} result(s)`}</span>
          {q && <span className="text-muted">substring: “{q}”</span>}
        </div>
        {rows.length === 0 ? (
          <div className="px-3 py-10 text-center text-sm text-muted">
            {busy ? "…" : "No contacts match. Try a shorter fragment, or crawl more sources."}
          </div>
        ) : (
          <ul className="divide-y divide-line">
            {rows.map((r) => (
              <li key={`${r.kind}:${r.value}`} className="flex items-center gap-3 px-3 py-2.5 hover:bg-panel">
                <KindIcon kind={r.kind} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-mono text-sm text-ink">{r.value}</span>
                  {r.sample_title && <span className="block truncate kai-metadata">{r.sample_title}</span>}
                </span>
                <span className="shrink-0 kai-metadata">{r.pages} page(s)</span>
                {r.sample_url && (
                  <a
                    href={r.sample_url}
                    target="_blank"
                    rel="noreferrer"
                    title={r.sample_url}
                    className="shrink-0 text-muted hover:text-accent"
                  >
                    <ExternalLink size={14} />
                  </a>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function Stat({ label, value, accent }: { label: string; value: number; accent?: boolean }) {
  return (
    <div className="border border-line bg-panel-2 px-3 py-3">
      <div className={`text-2xl font-semibold ${accent ? "text-accent" : "text-ink"}`}>{value.toLocaleString()}</div>
      <div className="kai-metadata mt-0.5">{label}</div>
    </div>
  );
}
