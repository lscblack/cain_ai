import { useEffect, useState } from "react";
import { ChevronLeft, ChevronRight, ExternalLink, Users, Sparkles, MapPin, Briefcase, AtSign, Phone, User2 } from "lucide-react";

import { api } from "@/lib/api";
import { AuthImg } from "@/components/AuthImg";

export interface Appearance {
  face_id: string;
  crop_url?: string | null;
  image_url?: string | null;
  source_url?: string | null;
  page_title?: string | null;
  caption?: string | null;
  similarity_pct: number;
  band: string;
}
export interface Person {
  person_id: string;
  name?: string | null;
  names: string[];
  emails: string[];
  phones: string[];
  usernames: string[];
  titles: string[];
  orgs: string[];
  locations: string[];
  age?: number | null;
  sex?: string | null;
  similarity_pct: number;
  band: string;
  crop_url?: string | null;
  appearance_count: number;
  appearances: Appearance[];
  description?: string | null;
}

const BAND_LABEL: Record<string, string> = {
  potential_match: "POTENTIAL MATCH",
  strong_similarity: "STRONG SIMILARITY",
  possible_association: "POSSIBLE ASSOCIATION",
  no_match: "NO MATCH",
};
const BAND_COLOR: Record<string, string> = {
  potential_match: "var(--kai-hud)",
  strong_similarity: "var(--kai-warn)",
  possible_association: "var(--kai-muted)",
  no_match: "var(--kai-muted)",
};
const bandFill = (b: string) =>
  b === "potential_match" ? 92 : b === "strong_similarity" ? 66 : b === "possible_association" ? 40 : 15;

function domainOf(url?: string | null): string {
  if (!url) return "unknown source";
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

function Bar({ label, pct, value }: { label: string; pct: number; value: string }) {
  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <span className="kai-metadata uppercase" style={{ color: "var(--kai-muted)" }}>{label}</span>
        <span className="hud-mono text-xs" style={{ color: "var(--kai-hud)" }}>{value}</span>
      </div>
      <div className="hud-bar">
        <span style={{ width: `${Math.max(0, Math.min(100, pct))}%` }} />
      </div>
    </div>
  );
}

/** Loadout-style 3-panel HUD: subject list · dossier · appearance viewer. */
export function FaceResultsHUD({
  people,
  queryUrl,
  maxAppearances,
  onOpenFrame,
}: {
  people: Person[];
  queryUrl: string | null;
  maxAppearances: number;
  onOpenFrame?: (a: Appearance) => void;
}) {
  const [sel, setSel] = useState(0);
  const [appIdx, setAppIdx] = useState(0);
  const [bio, setBio] = useState<{ loading: boolean; text?: string; model?: string | null } | null>(null);
  const [conns, setConns] = useState<{ loading: boolean; list?: any[] } | null>(null);

  const person = people[sel];

  useEffect(() => {
    setAppIdx(0);
    setBio(null);
    setConns(null);
  }, [sel]);

  const app = person?.appearances[appIdx];

  async function analyzeBio() {
    if (!person) return;
    setBio({ loading: true });
    try {
      const r = await api.post<{ bio: string; model: string | null }>("/intelligence/face/bio", {
        name: person.name,
        names: person.names,
        titles: person.titles,
        orgs: person.orgs,
        locations: person.locations,
        captions: person.appearances.map((a) => a.caption).filter(Boolean),
        sources: person.appearances.map((a) => a.source_url).filter(Boolean),
        age: person.age,
        sex: person.sex,
      });
      setBio({ loading: false, text: r.bio, model: r.model });
    } catch {
      setBio({ loading: false, text: "Bio analysis unavailable." });
    }
  }

  async function loadConnections() {
    if (!person) return;
    setConns({ loading: true });
    try {
      const r = await api.get<{ connections: any[] }>(
        `/intelligence/face/${person.person_id}/connections`,
      );
      setConns({ loading: false, list: r.connections ?? [] });
    } catch {
      setConns({ loading: false, list: [] });
    }
  }

  if (!person) return null;

  return (
    <div className="grid gap-3 lg:grid-cols-[230px_1fr_360px]">
      {/* LEFT — subjects */}
      <div className="hud-panel hud-frame p-2">
        <div className="hud-mono mb-2 px-1 text-xs uppercase" style={{ color: "var(--kai-hud)" }}>
          ◢ Subjects · {people.length}
        </div>
        <div className="space-y-1.5">
          {people.map((p, i) => (
            <button
              key={p.person_id}
              onClick={() => setSel(i)}
              className="flex w-full items-center gap-2 rounded px-1.5 py-1 text-left transition"
              style={{
                background: i === sel ? "rgba(34,211,238,0.10)" : "transparent",
                border: `1px solid ${i === sel ? "var(--kai-hud-dim)" : "transparent"}`,
              }}
            >
              <div className="h-9 w-9 shrink-0 overflow-hidden rounded border" style={{ borderColor: BAND_COLOR[p.band] }}>
                {p.crop_url ? (
                  <AuthImg path={p.crop_url} className="h-full w-full object-cover" />
                ) : (
                  <div className="flex h-full w-full items-center justify-center bg-panel-2"><User2 size={14} /></div>
                )}
              </div>
              <div className="min-w-0 flex-1">
                <div className="truncate text-xs" style={{ color: i === sel ? "var(--kai-hud)" : "var(--kai-text)" }}>
                  {p.name ?? `Subject ${i + 1}`}
                </div>
                <div className="kai-metadata">{p.similarity_pct}% · ×{p.appearance_count}</div>
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* CENTER — dossier */}
      <div className="hud-panel hud-frame p-4">
        <div className="mb-3 flex items-start justify-between">
          <div>
            <div className="hud-mono hud-glow text-lg" style={{ color: "var(--kai-hud)" }}>
              {(person.name ?? "UNKNOWN SUBJECT").toUpperCase()}
            </div>
            <div className="kai-metadata mt-0.5">
              {[person.sex, (person.age ?? 0) > 0 ? `~${person.age}y` : null].filter(Boolean).join(" · ") || "demographics n/a"}
            </div>
          </div>
          <span className="hud-mono text-xs" style={{ color: BAND_COLOR[person.band] }}>
            {BAND_LABEL[person.band] ?? person.band}
          </span>
        </div>

        <div className="mb-4 grid grid-cols-3 gap-3">
          <Bar label="Match" pct={person.similarity_pct} value={`${person.similarity_pct}%`} />
          <Bar label="Confidence" pct={bandFill(person.band)} value={(BAND_LABEL[person.band] ?? "").split(" ")[0] || "—"} />
          <Bar label="Footprint" pct={(person.appearance_count / Math.max(1, maxAppearances)) * 100} value={`${person.appearance_count} place${person.appearance_count === 1 ? "" : "s"}`} />
        </div>

        <div className="space-y-2">
          {(person.titles.length > 0 || person.orgs.length > 0) && (
            <Attr icon={<Briefcase size={13} />} label="Role" values={[...person.titles.slice(0, 2), ...person.orgs.slice(0, 2)]} />
          )}
          <Attr icon={<MapPin size={13} />} label="Location" values={person.locations} />
          <Attr icon={<User2 size={13} />} label="Aliases" values={person.names.slice(1, 6)} />
          <Attr icon={<AtSign size={13} />} label="Emails" values={person.emails} />
          <Attr icon={<Phone size={13} />} label="Phones" values={person.phones} />
          <Attr icon={<User2 size={13} />} label="Social" values={person.usernames} />
        </div>

        {/* AI BIO */}
        <div className="mt-4 border-t pt-3" style={{ borderColor: "var(--kai-border)" }}>
          {!bio ? (
            <button onClick={analyzeBio} className="flex items-center gap-1.5 hud-mono text-xs" style={{ color: "var(--kai-hud)" }}>
              <Sparkles size={13} /> ANALYZE BIO
            </button>
          ) : bio.loading ? (
            <div className="kai-metadata">analyzing…</div>
          ) : (
            <div>
              <div className="kai-metadata mb-1 uppercase" style={{ color: "var(--kai-hud)" }}>
                Bio {bio.model ? `· ${bio.model}` : "· composed"}
              </div>
              <div className="text-sm leading-relaxed" style={{ color: "var(--kai-text)" }}>{bio.text}</div>
            </div>
          )}
        </div>

        {/* CONNECTED */}
        <div className="mt-3 border-t pt-3" style={{ borderColor: "var(--kai-border)" }}>
          {!conns ? (
            <button onClick={loadConnections} className="flex items-center gap-1.5 hud-mono text-xs" style={{ color: "var(--kai-verified)" }}>
              <Users size={13} /> CONNECTED PEOPLE
            </button>
          ) : conns.loading ? (
            <div className="kai-metadata">finding connections…</div>
          ) : conns.list && conns.list.length > 0 ? (
            <div>
              <div className="kai-metadata mb-1 uppercase" style={{ color: "var(--kai-verified)" }}>
                {conns.list.length} connected — associates to observe
              </div>
              <div className="space-y-1">
                {conns.list.map((c: any) => (
                  <div key={c.face_id} className="flex items-center gap-2">
                    {c.crop_url && <AuthImg path={c.crop_url} className="h-7 w-7 shrink-0 rounded object-cover" />}
                    <span className="truncate text-xs">{c.names?.[0] ?? c.page_title ?? c.face_id.slice(0, 8)}</span>
                    <span className="kai-metadata ml-auto">{(c.reasons ?? [])[0] === "co_located" ? "same page" : (c.reasons ?? [])[0]}</span>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div className="kai-metadata">No connections found.</div>
          )}
        </div>
      </div>

      {/* RIGHT — appearance viewer */}
      <div className="hud-panel hud-frame flex flex-col p-3">
        <div className="hud-mono mb-2 text-xs uppercase" style={{ color: "var(--kai-hud)" }}>
          ◢ Appearance {appIdx + 1}/{person.appearances.length}
        </div>
        <div className="relative overflow-hidden rounded border hud-scanlines" style={{ borderColor: "var(--kai-hud-dim)", aspectRatio: "1 / 1" }}>
          {app?.crop_url ? (
            <AuthImg path={app.crop_url} className="h-full w-full object-cover" />
          ) : (
            <div className="flex h-full w-full items-center justify-center bg-panel-2"><User2 size={40} /></div>
          )}
          {person.appearances.length > 1 && (
            <>
              <button onClick={() => setAppIdx((i) => (i - 1 + person.appearances.length) % person.appearances.length)}
                className="absolute left-1 top-1/2 -translate-y-1/2 rounded bg-black/50 p-1" style={{ color: "var(--kai-hud)" }}>
                <ChevronLeft size={20} />
              </button>
              <button onClick={() => setAppIdx((i) => (i + 1) % person.appearances.length)}
                className="absolute right-1 top-1/2 -translate-y-1/2 rounded bg-black/50 p-1" style={{ color: "var(--kai-hud)" }}>
                <ChevronRight size={20} />
              </button>
            </>
          )}
          <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/80 to-transparent p-2">
            <div className="hud-mono truncate text-xs" style={{ color: "var(--kai-hud)" }}>
              {app?.page_title ?? domainOf(app?.source_url)}
            </div>
            <div className="kai-metadata">{domainOf(app?.source_url)} · {app?.similarity_pct}%</div>
          </div>
        </div>

        {/* filmstrip */}
        {person.appearances.length > 1 && (
          <div className="mt-2 flex gap-1.5 overflow-x-auto pb-1">
            {person.appearances.map((a, i) => (
              <button key={a.face_id + i} onClick={() => setAppIdx(i)}
                className="h-12 w-12 shrink-0 overflow-hidden rounded border"
                style={{ borderColor: i === appIdx ? "var(--kai-hud)" : "var(--kai-border)" }}>
                {a.crop_url ? <AuthImg path={a.crop_url} className="h-full w-full object-cover" /> : <div className="h-full w-full bg-panel-2" />}
              </button>
            ))}
          </div>
        )}

        {app?.source_url && (
          <div className="mt-3 flex flex-wrap gap-2">
            {onOpenFrame && (
              <button onClick={() => onOpenFrame(app)} className="rounded border px-2 py-1 text-xs hover:bg-panel" style={{ borderColor: "var(--kai-border)" }}>
                Open in frame
              </button>
            )}
            <a href={app.source_url} target="_blank" rel="noreferrer" className="flex items-center gap-1 rounded border px-2 py-1 text-xs hover:bg-panel" style={{ borderColor: "var(--kai-border)" }}>
              Source <ExternalLink size={11} />
            </a>
          </div>
        )}
        {queryUrl && (
          <div className="mt-3 border-t pt-2" style={{ borderColor: "var(--kai-border)" }}>
            <div className="kai-metadata mb-1 uppercase">Query</div>
            <img src={queryUrl} alt="query" className="h-14 w-14 rounded border object-cover" style={{ borderColor: "var(--kai-border)" }} />
          </div>
        )}
      </div>
    </div>
  );
}

function Attr({ icon, label, values }: { icon: React.ReactNode; label: string; values: string[] }) {
  if (!values.length) return null;
  return (
    <div className="flex gap-2">
      <span className="mt-0.5 shrink-0" style={{ color: "var(--kai-hud)" }}>{icon}</span>
      <div className="min-w-0">
        <div className="kai-metadata uppercase">{label}</div>
        <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-sm">
          {values.map((v, i) => <span key={i} className="truncate">{v}</span>)}
        </div>
      </div>
    </div>
  );
}
