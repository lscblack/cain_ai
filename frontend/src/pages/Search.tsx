import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Search as SearchIcon, Radar } from "lucide-react";

import { api } from "@/lib/api";
import type { SearchResponse } from "@/types";

const TYPE_COLORS: Record<string, string> = {
  phone: "var(--kai-verified)",
  email: "var(--kai-verified)",
  domain: "var(--kai-warn)",
  url: "var(--kai-warn)",
  username: "var(--kai-verified)",
  unknown: "var(--kai-muted)",
};

export function Search() {
  const [params, setParams] = useSearchParams();
  const initial = params.get("q") ?? "";
  const [q, setQ] = useState(initial);
  const [result, setResult] = useState<SearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [discovering, setDiscovering] = useState<string | null>(null); // the term being discovered
  const triggered = useRef<Set<string>>(new Set()); // dedup: never discover a term twice

  // When a name/phrase has no local match, kick a web discovery (deduped).
  async function autoDiscover(term: string) {
    const key = term.trim().toLowerCase();
    if (!key || triggered.current.has(key)) return;
    triggered.current.add(key);
    setDiscovering(term.trim());
    try {
      await api.post("/discovery/ask", { question: term.trim(), auto_crawl: true });
    } catch {
      triggered.current.delete(key); // allow retry if it failed to start
      setDiscovering(null);
    }
  }

  async function run(query: string) {
    if (!query.trim()) return;
    setLoading(true);
    try {
      const r = await api.get<SearchResponse>(`/search?q=${encodeURIComponent(query.trim())}`);
      setResult(r);
      // A name/phrase (unknown type) with nothing local -> discover it across the web.
      if (
        r.detected_type === "unknown" &&
        r.entity_matches.length === 0 &&
        r.evidence_matches.length === 0
      ) {
        void autoDiscover(query);
      }
    } catch {
      setResult(null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (initial) run(initial);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    setParams(q.trim() ? { q: q.trim() } : {});
    run(q);
  }

  return (
    <div>
      <form onSubmit={onSubmit} className="hud-panel hud-frame mb-6 flex items-center gap-2 px-4 py-3 focus-within:border-[color:var(--kai-hud)]">
        <SearchIcon size={16} style={{ color: "var(--kai-hud)" }} />
        <input
          autoFocus
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search phone / email / username / domain / url"
          className="w-full bg-transparent text-sm outline-none placeholder:text-muted"
        />
      </form>

      {loading && <div className="kai-metadata" style={{ color: "var(--kai-hud)" }}>Searching local corpus…</div>}

      {result && !loading && (
        <div>
          <div className="mb-4 flex items-center gap-2 kai-metadata">
            detected:
            <span style={{ color: TYPE_COLORS[result.detected_type] }}>
              {result.detected_type.toUpperCase()}
            </span>
            · normalized {result.normalized}
          </div>

          {discovering && (
            <Link
              to="/investigate"
              className="hud-panel hud-frame mb-6 flex items-center gap-3 px-4 py-3 transition hover:brightness-125"
            >
              <Radar size={16} className="animate-spin" style={{ color: "var(--kai-hud)", animationDuration: "3s" }} />
              <div>
                <div className="hud-mono text-xs uppercase" style={{ color: "var(--kai-hud)" }}>
                  ◢ Discovering “{discovering}” across the web
                </div>
                <div className="kai-metadata mt-0.5">
                  Crawling + scraping public sources — building an investigation case. Open{" "}
                  <span style={{ color: "var(--kai-hud)" }}>Investigate</span> to watch it fill.
                </div>
              </div>
            </Link>
          )}

          <section className="mb-6">
            <div className="hud-mono mb-2 uppercase text-xs" style={{ color: "var(--kai-hud)" }}>
              ◢ Entities ({result.entity_matches.length})
            </div>
            {result.entity_matches.length === 0 ? (
              <div className="text-sm text-muted">
                NO MATCH FOUND IN CURRENT INDEX
              </div>
            ) : (
              <div className="space-y-2">
                {result.entity_matches.map((e) => (
                  <div key={e.id} className="hud-panel flex items-center justify-between px-3 py-2">
                    <span className="text-sm">{e.value}</span>
                    <span className="kai-metadata uppercase">{e.type}</span>
                  </div>
                ))}
              </div>
            )}
          </section>

          <section>
            <div className="hud-mono mb-2 uppercase text-xs" style={{ color: "var(--kai-hud)" }}>
              ◢ Evidence ({result.evidence_matches.length})
            </div>
            {result.evidence_matches.length === 0 ? (
              <div className="text-sm text-muted">No source evidence in index.</div>
            ) : (
              <div className="space-y-2">
                {result.evidence_matches.map((ev) => (
                  <div key={ev.id} className="hud-panel px-3 py-2">
                    <a href={ev.source_url} target="_blank" rel="noreferrer" className="block truncate text-sm hover:underline">
                      {ev.source_url}
                    </a>
                    <div className="kai-metadata mt-1">
                      {ev.type} · collected {new Date(ev.collected_at).toLocaleString()}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
