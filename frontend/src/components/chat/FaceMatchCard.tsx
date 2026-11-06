import { useState } from "react";
import { ScanFace, Sparkles, FolderPlus, X, MapPin, Briefcase, AtSign, Phone, User2, IdCard } from "lucide-react";
import { AuthImg } from "@/components/AuthImg";
import type { FaceSearchResult, FacePerson } from "@/lib/faces";

function pctColor(pct: number): string {
  if (pct >= 70) return "var(--kai-verified)";
  if (pct >= 55) return "var(--kai-warn)";
  return "var(--kai-muted)";
}

function personTitle(p: FacePerson): string {
  return p.name || p.names?.[0] || "Unknown person";
}

/** A rich, editable prompt so the operator can continue the conversation about
 * this person — KAI gets the known attributes inline as grounding. */
function askPrompt(p: FacePerson): string {
  const title = personTitle(p);
  const lines = [
    `Tell me about this person from the face match and assess who they most likely are:`,
    `Name: ${title}`,
    p.names?.length > 1 ? `Also seen as: ${p.names.slice(0, 6).join(", ")}` : "",
    p.titles?.length ? `Titles: ${p.titles.slice(0, 4).join(", ")}` : "",
    p.orgs?.length ? `Orgs: ${p.orgs.slice(0, 4).join(", ")}` : "",
    p.locations?.length ? `Locations: ${p.locations.slice(0, 4).join(", ")}` : "",
    p.contexts?.length ? `Seen in: ${p.contexts.slice(0, 3).join(" | ")}` : "",
    `Similarity to my image: ${p.similarity_pct}% across ${p.appearance_count} appearance(s).`,
    `Research further (web if useful) and summarize who they are, with sources. Treat this as a potential match, not a confirmed identity.`,
  ];
  return lines.filter(Boolean).join("\n");
}

function Chips({ icon: Icon, items }: { icon: typeof MapPin; items?: string[] }) {
  if (!items || items.length === 0) return null;
  return (
    <div className="flex items-start gap-1.5">
      <Icon size={12} className="mt-0.5 shrink-0 text-muted" />
      <div className="flex flex-wrap gap-1">
        {items.slice(0, 12).map((v, i) => (
          <span key={i} className="rounded border border-line bg-panel-2 px-1.5 py-0.5 text-[11px]">{v}</span>
        ))}
      </div>
    </div>
  );
}

function PersonModal({ p, onClose, onAsk }: { p: FacePerson; onClose: () => void; onAsk?: (t: string) => void }) {
  const title = personTitle(p);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
      <div className="flex max-h-[85vh] w-full max-w-lg flex-col rounded-lg border border-line bg-panel shadow-xl"
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-line px-4 py-3">
          <div className="flex items-center gap-2">
            <ScanFace size={16} style={{ color: "var(--kai-hud)" }} />
            <span className="hud-mono text-sm" style={{ color: "var(--kai-hud)" }}>Face match</span>
          </div>
          <button onClick={onClose} className="text-muted hover:text-ink"><X size={16} /></button>
        </div>
        <div className="overflow-auto p-4">
          <div className="flex gap-3">
            {p.crop_url
              ? <AuthImg path={p.crop_url} className="h-24 w-24 shrink-0 rounded object-cover" />
              : <div className="h-24 w-24 shrink-0 rounded" style={{ background: "var(--kai-panel-2)" }} />}
            <div className="min-w-0 flex-1">
              <div className="text-base font-semibold">{title}</div>
              <div className="mt-0.5 flex items-center gap-2">
                <span className="hud-mono text-sm" style={{ color: pctColor(p.similarity_pct) }}>{p.similarity_pct}%</span>
                <span className="kai-metadata uppercase">{p.band?.replace(/_/g, " ")}</span>
                <span className="kai-metadata">· {p.appearance_count} appearance{p.appearance_count === 1 ? "" : "s"}</span>
              </div>
              {(p.age || p.sex) && <div className="kai-metadata mt-1">{[p.sex, p.age ? `~${p.age}y` : ""].filter(Boolean).join(" · ")}</div>}
              {p.description && <div className="mt-1 text-xs text-muted">{p.description}</div>}
            </div>
          </div>

          {p.nid && (
            <div className="mt-3 rounded border p-2" style={{ borderColor: "var(--kai-hud-dim)", background: "var(--kai-panel-2)" }}>
              <div className="mb-1 flex items-center gap-1.5">
                <IdCard size={13} style={{ color: "var(--kai-verified)" }} />
                <span className="hud-mono text-xs" style={{ color: "var(--kai-verified)" }}>National ID record</span>
                <span className="font-mono text-[11px] text-muted">{p.nid}</span>
              </div>
              <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-[11px]">
                {[["DOB", p.bio?.date_of_birth], ["Nationality", p.bio?.nationality],
                  ["Father", p.bio?.father_names], ["Mother", p.bio?.mother_names],
                  ["Place of birth", p.bio?.place_of_birth], ["Document", p.bio?.document_number]]
                  .filter(([, v]) => v)
                  .map(([k, v]) => (
                    <div key={k as string}><span className="text-muted">{k}: </span>{v as string}</div>
                  ))}
              </div>
              <a href={`/land-registry`} className="mt-1.5 inline-block text-[11px]" style={{ color: "var(--kai-hud)" }}>
                open in Land Registry →
              </a>
            </div>
          )}

          <div className="mt-3 grid gap-2">
            <Chips icon={User2} items={(p.names || []).filter((n) => n !== title)} />
            <Chips icon={Briefcase} items={[...(p.titles || []), ...(p.orgs || [])]} />
            <Chips icon={MapPin} items={p.locations} />
            <Chips icon={AtSign} items={[...(p.emails || []), ...(p.usernames || [])]} />
            <Chips icon={Phone} items={p.phones} />
          </div>

          {p.contexts && p.contexts.length > 0 && (
            <div className="mt-3">
              <div className="kai-metadata mb-1">contexts</div>
              <ul className="ml-4 list-disc text-xs text-muted">
                {p.contexts.slice(0, 6).map((c, i) => <li key={i}>{c}</li>)}
              </ul>
            </div>
          )}

          {p.appearances && p.appearances.length > 0 && (
            <div className="mt-3">
              <div className="kai-metadata mb-1">appearances ({p.appearances.length})</div>
              <div className="flex flex-wrap gap-2">
                {p.appearances.slice(0, 12).map((a) => (
                  <a key={a.face_id} href={a.source_url || "#"} target="_blank" rel="noopener noreferrer"
                    className="group relative" title={a.page_title || a.source_url || ""}>
                    {a.crop_url
                      ? <AuthImg path={a.crop_url} className="h-14 w-14 rounded border border-line object-cover" />
                      : <div className="h-14 w-14 rounded border border-line" style={{ background: "var(--kai-panel-2)" }} />}
                    <span className="absolute bottom-0 right-0 rounded-tl bg-black/70 px-1 text-[9px]" style={{ color: pctColor(a.similarity_pct) }}>
                      {a.similarity_pct}%
                    </span>
                  </a>
                ))}
              </div>
            </div>
          )}
        </div>
        {onAsk && (
          <div className="border-t border-line px-4 py-3">
            <button onClick={() => { onAsk(askPrompt(p)); onClose(); }}
              className="flex w-full items-center justify-center gap-2 rounded border px-3 py-2 text-sm hover:bg-panel-2"
              style={{ borderColor: "var(--kai-hud-dim)", color: "var(--kai-hud)" }}>
              <Sparkles size={14} /> Ask KAI about this person
            </button>
            <div className="kai-metadata mt-1.5 text-center">Scaffolds a prompt — edit it, then send to continue the conversation.</div>
          </div>
        )}
      </div>
    </div>
  );
}

function PersonRow({ p, onOpen }: { p: FacePerson; onOpen: () => void }) {
  const title = personTitle(p);
  const meta = [p.orgs?.[0], p.locations?.[0]].filter(Boolean).join(" · ");
  return (
    <button onClick={onOpen} className="flex w-full items-center gap-2 rounded border border-line bg-panel px-2 py-1.5 text-left hover:border-current"
      style={{ color: "inherit" }}>
      {p.crop_url
        ? <AuthImg path={p.crop_url} className="h-11 w-11 shrink-0 rounded object-cover" />
        : <div className="h-11 w-11 shrink-0 rounded" style={{ background: "var(--kai-panel-2)" }} />}
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <span className="truncate text-[12px]">{title}</span>
          <span className="hud-mono text-[10px]" style={{ color: pctColor(p.similarity_pct) }}>{p.similarity_pct}%</span>
          {p.nid && (
            <span className="flex shrink-0 items-center gap-0.5 rounded px-1 text-[10px]"
              style={{ background: "var(--kai-panel-2)", color: "var(--kai-verified)" }}>
              <IdCard size={10} /> NID
            </span>
          )}
        </div>
        {p.nid && <div className="kai-metadata truncate font-mono">ID {p.nid}</div>}
        {meta && <div className="kai-metadata truncate">{meta}</div>}
        <div className="kai-metadata">{p.appearance_count} appearance{p.appearance_count === 1 ? "" : "s"} · click for details</div>
      </div>
      <Sparkles size={12} className="shrink-0 text-muted" />
    </button>
  );
}

export function FaceMatchCard({ r, onAsk }: { r: FaceSearchResult; onAsk?: (t: string) => void }) {
  const people = r.people || [];
  const [open, setOpen] = useState<FacePerson | null>(null);
  return (
    <div className="mt-2 overflow-hidden rounded-md border" style={{ borderColor: "#262b36", background: "#0b0e14" }}>
      <div className="flex items-center gap-1.5 border-b px-2 py-1" style={{ borderColor: "#1a1e27", background: "#11151d" }}>
        <ScanFace size={12} style={{ color: "var(--kai-hud)" }} />
        <span className="font-mono text-[10px]" style={{ color: "#6b7280" }}>
          face search · {r.faces_detected} face{r.faces_detected === 1 ? "" : "s"} detected
          {typeof r.indexed_faces === "number" ? ` · ${r.indexed_faces} indexed` : ""}
        </span>
      </div>
      <div className="p-2">
        {r.faces_detected === 0 && (
          <div className="text-[11px] text-muted">No face detected in the uploaded image.</div>
        )}
        {r.faces_detected > 0 && people.length === 0 && (
          <div className="flex items-center gap-2 text-[11px] text-muted">
            <FolderPlus size={12} /> No match in the local index yet.
            {onAsk && (
              <button onClick={() => onAsk("Enroll the face I just uploaded into a new investigation and search the web for matches.")}
                className="rounded border border-line px-1.5 py-0.5 hover:bg-panel-2" style={{ color: "var(--kai-hud)" }}>
                enroll + search
              </button>
            )}
          </div>
        )}
        <div className="grid gap-1">
          {people.map((p) => <PersonRow key={p.person_id} p={p} onOpen={() => setOpen(p)} />)}
        </div>
        {r.note && <div className="kai-metadata mt-1.5">{r.note}</div>}
      </div>
      {open && <PersonModal p={open} onClose={() => setOpen(null)} onAsk={onAsk} />}
    </div>
  );
}
