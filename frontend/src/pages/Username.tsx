import { useState, type FormEvent } from "react";
import { AtSign, ExternalLink } from "lucide-react";

import { api } from "@/lib/api";
import type { UsernameIntelligence } from "@/types";

const STATUS_COLOR: Record<string, string> = {
  found: "var(--kai-verified)",
  not_found: "var(--kai-muted)",
  unknown: "var(--kai-warn)",
  error: "var(--kai-accent)",
};

export function Username() {
  const [username, setUsername] = useState("");
  const [result, setResult] = useState<UsernameIntelligence | null>(null);
  const [loading, setLoading] = useState(false);
  const [avatarMsg, setAvatarMsg] = useState<string | null>(null);
  const [indexing, setIndexing] = useState(false);

  async function indexAvatars() {
    if (!username.trim()) return;
    setIndexing(true);
    setAvatarMsg(null);
    try {
      const r = await api.post<{ faces_indexed: number; results: any[] }>(
        "/intelligence/username/index-avatars",
        { username: username.trim() },
      );
      const withAvatar = r.results.filter((x) => x.avatar).length;
      setAvatarMsg(`Indexed ${r.faces_indexed} face(s) from ${withAvatar} avatar(s). Now searchable in Faces → 1:N Search.`);
    } catch (e: any) {
      setAvatarMsg(
        e?.detail === "face_engine_unavailable"
          ? "Face engine unavailable."
          : "Avatar indexing failed (unavatar free tier is 25/day; add a key in Power Up).",
      );
    } finally {
      setIndexing(false);
    }
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!username.trim()) return;
    setLoading(true);
    try {
      setResult(
        await api.post<UsernameIntelligence>("/intelligence/username", {
          username: username.trim(),
        }),
      );
    } catch {
      setResult(null);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <div className="mb-5 flex items-center gap-2">
        <AtSign size={18} className="text-muted" />
        <h1 className="text-lg font-semibold">Username Intelligence</h1>
      </div>

      <form onSubmit={onSubmit} className="mb-6 flex gap-2">
        <input
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          placeholder="handle (e.g. osint_guy)"
          className="flex-1 rounded-md border border-line bg-panel px-3 py-2 text-sm outline-none focus:border-muted"
        />
        <button className="rounded-md border border-line bg-panel px-4 py-2 text-sm hover:bg-panel-2">
          Check
        </button>
        <button type="button" onClick={indexAvatars} disabled={indexing} className="rounded-md border border-line bg-panel px-4 py-2 text-sm hover:bg-panel-2 disabled:opacity-50">
          {indexing ? "Indexing…" : "Index avatars"}
        </button>
      </form>
      {avatarMsg && <div className="mb-4 kai-metadata" style={{ color: "var(--kai-verified)" }}>{avatarMsg}</div>}

      {loading && <div className="kai-metadata">Checking public profiles…</div>}

      {result && !loading && (
        <>
          <div className="mb-4 kai-metadata">
            {result.found_count} reachable public profile(s) for{" "}
            <span className="text-ink">{result.username}</span>
          </div>
          <div className="grid gap-2 md:grid-cols-2">
            {result.results.map((h) => (
              <a
                key={h.platform}
                href={h.url}
                target="_blank"
                rel="noreferrer"
                className="flex items-center justify-between rounded-md border border-line bg-panel px-3 py-2 hover:border-muted"
              >
                <div className="flex items-center gap-2">
                  <span
                    className="inline-block h-2 w-2 rounded-full"
                    style={{ background: STATUS_COLOR[h.status] }}
                  />
                  <span className="text-sm">{h.name}</span>
                </div>
                <span className="flex items-center gap-2 kai-metadata uppercase">
                  {h.status.replace("_", " ")}
                  <ExternalLink size={12} />
                </span>
              </a>
            ))}
          </div>
          <div className="kai-metadata mt-4 border-t border-line pt-3" style={{ color: "var(--kai-warn)" }}>
            {result.note}
          </div>
        </>
      )}
    </div>
  );
}
