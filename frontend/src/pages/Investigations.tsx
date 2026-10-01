import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { motion } from "framer-motion";
import { Plus, FolderSearch } from "lucide-react";

import { investigationsApi } from "@/lib/investigations";
import type { InvestigationDetail } from "@/types";

export function Investigations() {
  const [cases, setCases] = useState<InvestigationDetail[]>([]);
  const [name, setName] = useState("");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    try {
      setCases(await investigationsApi.list());
    } catch {
      setError("Failed to load investigations.");
    }
  }

  useEffect(() => {
    load();
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

  return (
    <div>
      <div className="mb-5 flex items-center gap-2">
        <FolderSearch size={18} className="text-muted" />
        <h1 className="text-lg font-semibold">Investigations</h1>
      </div>

      <form onSubmit={onCreate} className="mb-6 flex gap-2">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="New investigation name (e.g. Subject Investigation 001)"
          className="flex-1 rounded-md border border-line bg-panel px-3 py-2 text-sm outline-none focus:border-muted"
        />
        <button
          type="submit"
          disabled={creating}
          className="flex items-center gap-2 rounded-md border border-line bg-panel px-4 py-2 text-sm hover:bg-panel-2 disabled:opacity-50"
        >
          <Plus size={15} /> Create
        </button>
      </form>

      {error && <div className="mb-4 text-sm" style={{ color: "var(--kai-accent)" }}>{error}</div>}

      {cases.length === 0 ? (
        <div className="rounded-lg border border-line bg-panel p-6 text-sm text-muted">
          No investigations yet. Create one above to begin.
        </div>
      ) : (
        <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
          {cases.map((c, i) => (
            <motion.div
              key={c.id}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.03 }}
            >
              <Link
                to={`/investigations/${c.id}`}
                className="block rounded-lg border border-line bg-panel p-4 hover:border-muted"
              >
                <div className="flex items-center justify-between">
                  <span className="kai-metadata">{c.code}</span>
                  <span
                    className="kai-metadata uppercase"
                    style={{ color: c.status === "open" ? "var(--kai-verified)" : "var(--kai-muted)" }}
                  >
                    {c.status}
                  </span>
                </div>
                <div className="mt-2 truncate text-sm font-medium">{c.name}</div>
                <div className="kai-metadata mt-3 flex gap-3">
                  <span>ent {c.entity_count}</span>
                  <span>evd {c.evidence_count}</span>
                  <span>rel {c.relationship_count}</span>
                </div>
              </Link>
            </motion.div>
          ))}
        </div>
      )}
    </div>
  );
}
