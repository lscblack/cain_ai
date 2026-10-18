import { useEffect, useState, type FormEvent } from "react";
import { motion } from "framer-motion";
import { Plus, FolderSearch } from "lucide-react";

import { api } from "@/lib/api";
import { investigationsApi } from "@/lib/investigations";
import { FolderCard } from "@/components/FolderCard";
import { PageLoading, ErrorRetry } from "@/components/Async";
import type { InvestigationDetail } from "@/types";

interface DiscoveryRun {
  id: string;
  status: string;
  names: string[];
  approved: number;
  progress: number;
}

export function Investigations() {
  const [cases, setCases] = useState<InvestigationDetail[]>([]);
  const [runs, setRuns] = useState<DiscoveryRun[]>([]);
  const [name, setName] = useState("");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  async function load() {
    try {
      setCases(await investigationsApi.list());
      setError(null);
    } catch {
      setError("Failed to load investigations.");
    } finally {
      setLoaded(true);
    }
    try {
      const r = await api.get<{ investigations: DiscoveryRun[] }>("/discovery/investigations");
      setRuns(r.investigations ?? []);
    } catch {
      /* discovery optional */
    }
  }

  useEffect(() => {
    load();
    const t = setInterval(load, 5000); // keep discovery-case status fresh
    return () => clearInterval(t);
  }, []);

  async function onCreate(e: FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setCreating(true);
    setError(null);
    try {
      await investigationsApi.create(name.trim());
      setName("");
      await load();
    } catch {
      setError("Failed to create investigation.");
    } finally {
      setCreating(false);
    }
  }

  const runColor = (s: string) =>
    s === "done" ? "var(--kai-verified)" : s === "queued" ? "var(--kai-warn)" : "var(--kai-hud)";

  async function deleteDiscovery(id: string, label: string) {
    if (!window.confirm(`Delete discovery case “${label}”?\n\nThis removes the case folder. Collected sources/pages stay in the corpus.`)) return;
    setRuns((cur) => cur.filter((r) => r.id !== id)); // optimistic
    try {
      await investigationsApi.removeDiscovery(id);
    } catch {
      setError("Failed to delete case.");
      await load();
    }
  }

  async function deleteManual(id: string, label: string) {
    if (!window.confirm(`Delete case “${label}”?\n\nThis permanently removes the case and its entities, evidence and relationships.`)) return;
    setCases((cur) => cur.filter((c) => c.id !== id)); // optimistic
    try {
      await investigationsApi.remove(id);
    } catch {
      setError("Failed to delete case.");
      await load();
    }
  }

  return (
    <div>
      <div className="mb-5 flex items-center gap-2">
        <FolderSearch size={18} style={{ color: "var(--kai-hud)" }} />
        <h1 className="hud-mono text-lg font-semibold hud-glow" style={{ color: "var(--kai-hud)" }}>
          Investigations
        </h1>
      </div>

      <form onSubmit={onCreate} className="hud-panel hud-frame mb-6 flex gap-2 p-2">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="New case name (e.g. Subject Investigation 001)"
          className="flex-1 rounded-md border border-line bg-panel px-3 py-2 text-sm outline-none focus:border-[color:var(--kai-hud)]"
        />
        <button
          type="submit"
          disabled={creating}
          className="flex items-center gap-2 rounded-md border px-4 py-2 text-sm disabled:opacity-50"
          style={{ borderColor: "var(--kai-hud-dim)", color: "var(--kai-hud)", background: "rgba(34,211,238,0.06)" }}
        >
          <Plus size={15} /> Create
        </button>
      </form>

      {error && <div className="mb-4 text-sm" style={{ color: "var(--kai-accent)" }}>{error}</div>}

      {/* Discovery cases (started from a name search / Ask) */}
      {runs.length > 0 && (
        <section className="mb-8">
          <div className="hud-mono mb-3 text-xs uppercase hud-glow" style={{ color: "var(--kai-hud)" }}>
            ◢ Discovery cases · {runs.length}
          </div>
          <div className="grid gap-x-3 gap-y-5 md:grid-cols-2 lg:grid-cols-3">
            {runs.map((r, i) => (
              <motion.div key={r.id} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.03 }}>
                <FolderCard
                  to={`/investigate?run=${r.id}`}
                  code={r.id.slice(0, 10)}
                  title={r.names.join(", ") || "subject"}
                  status={r.status === "done" ? "READY" : r.status.toUpperCase()}
                  statusColor={runColor(r.status)}
                  meta={[
                    { label: "subjects", value: r.names.length },
                    { label: "sources", value: r.approved },
                    ...(r.status !== "done" ? [{ label: "progress", value: `${r.progress}%` }] : []),
                  ]}
                  onDelete={() => deleteDiscovery(r.id, r.names.join(", ") || "subject")}
                />
              </motion.div>
            ))}
          </div>
        </section>
      )}

      {/* Manual cases */}
      <div className="hud-mono mb-3 text-xs uppercase" style={{ color: "var(--kai-muted)" }}>
        ◢ Manual cases · {cases.length}
      </div>
      {!loaded ? (
        <PageLoading label="Loading investigations…" />
      ) : error && cases.length === 0 ? (
        <ErrorRetry error={error} onRetry={load} />
      ) : cases.length === 0 ? (
        <div className="rounded-lg border border-line bg-panel p-6 text-sm text-muted">
          No manual cases yet. Create one above, or search a name to start a discovery case.
        </div>
      ) : (
        <div className="grid gap-x-3 gap-y-5 md:grid-cols-2 lg:grid-cols-3">
          {cases.map((c, i) => (
            <motion.div key={c.id} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.03 }}>
              <FolderCard
                to={`/investigations/${c.id}`}
                code={c.code}
                title={c.name}
                status={c.status.toUpperCase()}
                statusColor={c.status === "open" ? "var(--kai-verified)" : "var(--kai-muted)"}
                meta={[
                  { label: "ent", value: c.entity_count },
                  { label: "evd", value: c.evidence_count },
                  { label: "rel", value: c.relationship_count },
                ]}
                onDelete={() => deleteManual(c.id, c.name)}
              />
            </motion.div>
          ))}
        </div>
      )}
    </div>
  );
}
