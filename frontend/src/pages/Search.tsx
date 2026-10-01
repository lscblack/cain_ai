import { useEffect, useState, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { Search as SearchIcon } from "lucide-react";

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

  async function run(query: string) {
    if (!query.trim()) return;
    setLoading(true);
    try {
      setResult(await api.get<SearchResponse>(`/search?q=${encodeURIComponent(query.trim())}`));
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
      <form onSubmit={onSubmit} className="mb-6 flex items-center gap-2 rounded-lg border border-line bg-panel px-4 py-3">
        <SearchIcon size={16} className="text-muted" />
        <input
          autoFocus
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search phone / email / username / domain / url"
          className="w-full bg-transparent text-sm outline-none placeholder:text-muted"
        />
      </form>

      {loading && <div className="kai-metadata">Searching local corpus…</div>}

      {result && !loading && (
        <div>
          <div className="mb-4 flex items-center gap-2 kai-metadata">
            detected:
            <span style={{ color: TYPE_COLORS[result.detected_type] }}>
              {result.detected_type.toUpperCase()}
            </span>
            · normalized {result.normalized}
          </div>

          <section className="mb-6">
            <div className="kai-metadata mb-2 uppercase">
              Entities ({result.entity_matches.length})
            </div>
            {result.entity_matches.length === 0 ? (
              <div className="text-sm text-muted">
                NO MATCH FOUND IN CURRENT INDEX
              </div>
            ) : (
              <div className="space-y-2">
                {result.entity_matches.map((e) => (
                  <div key={e.id} className="flex items-center justify-between rounded-md border border-line bg-panel px-3 py-2">
                    <span className="text-sm">{e.value}</span>
                    <span className="kai-metadata uppercase">{e.type}</span>
                  </div>
                ))}
              </div>
            )}
          </section>

          <section>
            <div className="kai-metadata mb-2 uppercase">
              Evidence ({result.evidence_matches.length})
            </div>
            {result.evidence_matches.length === 0 ? (
              <div className="text-sm text-muted">No source evidence in index.</div>
            ) : (
              <div className="space-y-2">
                {result.evidence_matches.map((ev) => (
                  <div key={ev.id} className="rounded-md border border-line bg-panel px-3 py-2">
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
