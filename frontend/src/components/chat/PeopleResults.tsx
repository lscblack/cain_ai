import { useState } from "react";
import { IdCard, Phone, MapPin, Users, ExternalLink, ChevronLeft, ChevronRight, Network, Globe } from "lucide-react";
import { AuthImg } from "@/components/AuthImg";
import { WebFaceModal } from "@/components/chat/WebFaceModal";
import { InvestigatePanel } from "@/components/chat/InvestigatePanel";
import type { FaceMatch, PeopleSearchResult, PersonCardData, Relative, WebFace, WebMatch } from "@/lib/enrich";

function pctColor(pct: number): string {
  if (pct >= 70) return "var(--kai-verified)";
  if (pct >= 55) return "var(--kai-warn)";
  return "var(--kai-muted)";
}

function Photo({ url, size }: { url?: string | null; size: number }) {
  const s = { width: size, height: size };
  return url
    ? <AuthImg path={url} className="shrink-0 rounded border border-line object-cover" style={s} />
    : <div className="shrink-0 rounded border border-line" style={{ ...s, background: "var(--kai-panel-2)" }} />;
}

const REL_TITLE: Record<string, string> = { father: "Father", mother: "Mother", sibling: "Sibling", child: "Child", extended: "Relative" };

function RelativeChip({ r }: { r: Relative }) {
  const sure = r.confidence >= 100;
  return (
    <div className="flex items-center gap-2 rounded border border-line bg-panel p-1.5" title={r.reasons.join(" · ")}>
      <Photo url={r.photo_url} size={40} />
      <div className="min-w-0">
        <div className="truncate text-xs font-medium">{r.name}</div>
        <div className="kai-metadata truncate">
          {r.relation === "extended" ? r.label : (REL_TITLE[r.relation] || r.relation)} ·{" "}
          <span style={{ color: sure ? "var(--kai-verified)" : pctColor(r.confidence) }}>
            {sure && r.relation === "sibling" ? "100% sibling" : `${r.confidence}%`}
          </span>
          {r.village || r.cell ? ` · ${[r.village, r.cell].filter(Boolean).join(", ")}` : ""}
        </div>
        <div className="kai-metadata truncate font-mono">{r.nid}</div>
      </div>
    </div>
  );
}

function ParentCard({ r }: { r: Relative }) {
  const where = [r.village, r.cell, r.sector, r.district].filter(Boolean).join(", ");
  const facts: [string, string | null | undefined][] = [
    ["NID", r.nid], ["Born", r.date_of_birth], ["Place of birth", r.place_of_birth],
    ["Nationality", r.nationality], ["Marital status", r.marital_status],
    ["Father", r.father_names], ["Mother", r.mother_names], ["Lives", where],
    ["Phones", r.phones && r.phones.length ? r.phones.join(", ") : null],
  ];
  const kids = r.children || [];
  return (
    <div className="rounded border border-line bg-panel p-2" title={r.reasons.join(" · ")}>
      <div className="flex gap-2">
        <Photo url={r.photo_url} size={56} />
        <div className="min-w-0 flex-1">
          <div className="text-xs font-semibold">
            {REL_TITLE[r.relation]}: {r.name}{" "}
            <span className="hud-mono" style={{ color: pctColor(r.confidence) }}>{r.confidence}%</span>
          </div>
          <div className="mt-0.5 grid grid-cols-1 gap-x-3 text-[11px] sm:grid-cols-2">
            {facts.filter(([, v]) => v).map(([k, v]) => (
              <div key={k} className="truncate"><span className="text-muted">{k}: </span>{v}</div>
            ))}
          </div>
        </div>
      </div>
      {kids.length > 0 && (
        <div className="mt-2">
          <div className="kai-metadata mb-1">All people recorded as {r.name}&rsquo;s children ({kids.length})</div>
          <div className="grid gap-1.5 sm:grid-cols-2">
            {kids.map((c) => (
              <div key={c.nid} className="flex items-center gap-2 rounded border border-line p-1"
                style={c.is_subject ? { borderColor: "var(--kai-hud)" } : undefined}>
                <Photo url={c.photo_url} size={32} />
                <div className="min-w-0">
                  <div className="truncate text-[11px] font-medium">{c.name}{c.is_subject ? " (this person)" : ""}</div>
                  <div className="kai-metadata truncate">
                    {[c.date_of_birth, c.village || c.cell, c.nid].filter(Boolean).join(" · ")}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function WebFaceInfo({ w }: { w: WebFace }) {
  const [open, setOpen] = useState(false);
  const rows: [string, string[] | undefined][] = [
    ["Names", w.names], ["Titles", w.titles], ["Organisations", w.orgs], ["Phones", w.phones],
    ["Emails", w.emails], ["Usernames", w.usernames], ["Locations", w.locations],
  ];
  return (
    <div className="flex gap-2 rounded border border-line bg-panel p-2">
      <button onClick={() => setOpen(true)} className="relative shrink-0" title="Show everything crawled for this face">
        <Photo url={w.crop_url} size={64} />
        <span className="absolute bottom-0 right-0 rounded-tl bg-black/70 px-1 text-[9px]" style={{ color: pctColor(w.match_pct) }}>
          {w.match_pct}%
        </span>
      </button>
      <div className="min-w-0 flex-1 text-[11px]">
        <button onClick={() => setOpen(true)} className="flex max-w-full items-center gap-1 text-left font-medium hover:underline"
          style={{ color: "var(--kai-hud)" }} title="Show everything crawled for this face">
          <Globe size={11} className="shrink-0" /> <span className="truncate">{w.page_title || w.source_url || "web face"}</span>
        </button>
        {w.source_url && (
          <a href={w.source_url} target="_blank" rel="noopener noreferrer" className="kai-metadata flex items-center gap-1 truncate hover:underline">
            <ExternalLink size={10} className="shrink-0" /> {w.source_url}
          </a>
        )}
        {(w.caption || w.context) && <div className="mt-0.5 text-muted">{w.caption || w.context}</div>}
        {(w.sex || w.age) && <div className="kai-metadata">{[w.sex, w.age ? `~${w.age}y` : ""].filter(Boolean).join(" · ")}</div>}
        <div className="mt-0.5 grid gap-0.5">
          {rows.filter(([, v]) => v && v.length).map(([k, v]) => (
            <div key={k}><span className="text-muted">{k}: </span>{v!.slice(0, 8).join(", ")}</div>
          ))}
        </div>
        <button onClick={() => setOpen(true)} className="mt-1 rounded border border-line px-2 py-0.5 hover:bg-panel-2"
          style={{ color: "var(--kai-hud)" }}>
          Open full web details
        </button>
      </div>
      {open && <WebFaceModal faceId={w.face_id} onClose={() => setOpen(false)} />}
    </div>
  );
}

function PersonCard({ p }: { p: PersonCardData }) {
  const rel = p.relatives;
  const groups: [string, Relative[]][] = rel
    ? [["Parents", rel.parents], ["Siblings", rel.siblings], ["Children", rel.children]]
    : [];
  const where = [p.village, p.cell, p.sector, p.district, p.province].filter(Boolean).join(", ");
  const facts: [string, string | null | undefined][] = [
    ["Sex", p.sex], ["Born", p.date_of_birth], ["Place of birth", p.place_of_birth],
    ["Nationality", p.nationality], ["Marital status", p.marital_status],
    ["Document no.", p.document_number],
    ["Land parcels", p.upis && p.upis.length ? p.upis.join(", ") : null],
  ];
  return (
    <div className="rounded border border-line bg-panel-2 p-3">
      <div className="flex gap-3">
        <Photo url={p.photo_url} size={88} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-semibold">{p.name}</span>
            {p.match_pct != null && (
              <span className="hud-mono text-sm" style={{ color: pctColor(p.match_pct) }}>{p.match_pct}% face match</span>
            )}
            {p.matched_by.filter((m) => m !== "face").map((m) => (
              <span key={m} className="kai-metadata uppercase">via {m}</span>
            ))}
          </div>
          <div className="mt-0.5 flex items-center gap-1 font-mono text-[11px] text-muted"><IdCard size={11} /> {p.nid}</div>
          <div className="mt-1 grid grid-cols-1 gap-x-3 gap-y-0.5 text-[11px] sm:grid-cols-2">
            {facts.filter(([, v]) => v).map(([k, v]) => (
              <div key={k}><span className="text-muted">{k}: </span>{v}</div>
            ))}
          </div>
          {(p.father_names || p.mother_names) && (
            <div className="mt-1 text-[11px]">
              {p.father_names && <span><span className="text-muted">Father: </span>{p.father_names}  </span>}
              {p.mother_names && <span><span className="text-muted">Mother: </span>{p.mother_names}</span>}
            </div>
          )}
          {where && <div className="mt-1 flex items-center gap-1 text-[11px]"><MapPin size={11} className="text-muted" />{where}</div>}
          {p.phones.length > 0 && (
            <div className="mt-1 flex items-center gap-1 text-[11px]"><Phone size={11} className="text-muted" />{p.phones.slice(0, 5).join(", ")}</div>
          )}
        </div>
      </div>
      {p.web_photos && p.web_photos.length > 0 && (
        <div className="mt-3 border-t border-line pt-2">
          <div className="mb-1 flex items-center gap-1.5">
            <Globe size={12} style={{ color: "var(--kai-hud)" }} />
            <span className="hud-mono text-[11px]" style={{ color: "var(--kai-hud)" }}>
              Found on the web ({p.web_photos.length})
            </span>
          </div>
          <div className="grid gap-2">
            {p.web_photos.map((w) => <WebFaceInfo key={w.face_id} w={w} />)}
          </div>
        </div>
      )}
      {rel?.extended && rel.extended.length > 0 && (
        <div className="mt-3 border-t border-line pt-2">
          <div className="mb-1 flex items-center gap-1.5">
            <Network size={12} style={{ color: "var(--kai-hud)" }} />
            <span className="hud-mono text-[11px]" style={{ color: "var(--kai-hud)" }}>
              Extended family ({rel.extended.length})
            </span>
          </div>
          {Object.entries(
            rel.extended.reduce<Record<string, Relative[]>>((acc, r) => {
              const key = r.label.replace(/^(uncle|aunt)$/, "uncles & aunts")
                .replace(/^(grandfather|grandmother|grandparent)$/, "grandparents")
                .replace(/^(nephew|niece|nephew\/niece)$/, "nephews & nieces")
                .replace(/^cousin$/, "cousins");
              (acc[key] ||= []).push(r);
              return acc;
            }, {}),
          ).map(([label, list]) => (
            <div key={label} className="mb-2">
              <div className="kai-metadata mb-1 capitalize">{label} ({list.length})</div>
              <div className="grid gap-1.5 sm:grid-cols-2">
                {list.map((r) => <RelativeChip key={r.nid} r={r} />)}
              </div>
            </div>
          ))}
        </div>
      )}
      {rel && !groups.some(([, l]) => l.length > 0) && !(rel.extended && rel.extended.length) && (
        <div className="kai-metadata mt-2 border-t border-line pt-2">
          No parents, siblings or children found in the saved database yet.
        </div>
      )}
      {groups.some(([, l]) => l.length > 0) && (
        <div className="mt-3 border-t border-line pt-2">
          <div className="mb-1 flex items-center gap-1.5">
            <Users size={12} style={{ color: "var(--kai-hud)" }} />
            <span className="hud-mono text-[11px]" style={{ color: "var(--kai-hud)" }}>Family found in system</span>
          </div>
          {groups.filter(([, l]) => l.length > 0).map(([title, list]) => (
            <div key={title} className="mb-2">
              <div className="kai-metadata mb-1">{title} ({list.length})</div>
              {title === "Parents"
                ? <div className="grid gap-1.5">{list.map((r) => <ParentCard key={r.nid + r.relation} r={r} />)}</div>
                : <div className="grid gap-1.5 sm:grid-cols-2">{list.map((r) => <RelativeChip key={r.nid + r.relation} r={r} />)}</div>}
            </div>
          ))}
        </div>
      )}
      <InvestigatePanel nid={p.nid} name={p.name} />
    </div>
  );
}

function WebCard({ m }: { m: WebMatch }) {
  return (
    <a href={m.source_url || "#"} target="_blank" rel="noopener noreferrer"
      className="flex items-center gap-2 rounded border border-line bg-panel p-1.5 hover:bg-panel-2">
      <Photo url={m.crop_url} size={48} />
      <div className="min-w-0 flex-1">
        <div className="truncate text-xs">{m.names[0] || m.page_title || m.source_url || "web match"}</div>
        <div className="kai-metadata truncate">{[...m.phones, ...m.locations].slice(0, 3).join(" · ")}</div>
      </div>
      <span className="hud-mono text-xs" style={{ color: pctColor(m.match_pct) }}>{m.match_pct}%</span>
      <ExternalLink size={11} className="text-muted" />
    </a>
  );
}

function FaceSlider({ matches, people, min }: { matches: FaceMatch[]; people: PersonCardData[]; min: number }) {
  const [i, setI] = useState(0);
  const [detail, setDetail] = useState<string | null>(null);
  const m = matches[Math.min(i, matches.length - 1)];
  const linked = m.linked_nid ? people.find((p) => p.nid === m.linked_nid) : undefined;
  const go = (d: number) => setI((v) => (v + d + matches.length) % matches.length);
  const facts: [string, string[]][] = [
    ["Names", m.names], ["Phones", m.phones], ["Emails", m.emails], ["Usernames", m.usernames],
    ["Titles", m.titles], ["Orgs", m.orgs], ["Locations", m.locations],
  ];
  return (
    <div className="rounded border border-line bg-panel-2 p-3">
      <div className="mb-2 flex items-center justify-between">
        <span className="hud-mono text-[11px]" style={{ color: "var(--kai-hud)" }}>
          Face index matches ≥ {min}% · {i + 1} / {matches.length}
        </span>
        <div className="flex gap-1">
          <button onClick={() => go(-1)} disabled={matches.length < 2} aria-label="Previous match"
            className="rounded border border-line p-1 hover:bg-panel disabled:opacity-40"><ChevronLeft size={14} /></button>
          <button onClick={() => go(1)} disabled={matches.length < 2} aria-label="Next match"
            className="rounded border border-line p-1 hover:bg-panel disabled:opacity-40"><ChevronRight size={14} /></button>
        </div>
      </div>

      {/* thumbnail strip — click to switch */}
      <div className="mb-3 flex gap-1.5 overflow-x-auto pb-1">
        {matches.map((x, k) => (
          <button key={x.face_id} onClick={() => setI(k)} className="relative shrink-0 rounded"
            style={{ outline: k === i ? "2px solid var(--kai-hud)" : "none" }}
            title={`${x.names[0] || x.page_title || "match"} — ${x.match_pct}%`}>
            <Photo url={x.crop_url} size={48} />
            <span className="absolute bottom-0 right-0 rounded-tl bg-black/70 px-1 text-[9px]" style={{ color: pctColor(x.match_pct) }}>
              {Math.round(x.match_pct)}%
            </span>
            {x.linked_nid && <IdCard size={10} className="absolute left-0.5 top-0.5" style={{ color: "var(--kai-verified)" }} />}
          </button>
        ))}
      </div>

      {detail && <WebFaceModal faceId={detail} onClose={() => setDetail(null)} />}
      <div className="flex gap-3">
        <button onClick={() => m.kind === "web" && setDetail(m.face_id)} className="shrink-0"
          title={m.kind === "web" ? "Show everything crawled for this face" : "ID photo"}>
          <Photo url={m.crop_url} size={120} />
        </button>
        <div className="min-w-0 flex-1 text-[11px]">
          <div className="flex flex-wrap items-center gap-2">
            <span className="hud-mono text-sm" style={{ color: pctColor(m.match_pct) }}>{m.match_pct}% match</span>
            <span className="kai-metadata uppercase">{m.kind === "nid" ? "ID photo" : "web face"}</span>
            {m.linked_by && <span className="kai-metadata">linked by {m.linked_by}</span>}
          </div>
          {(m.page_title || m.source_url) && (
            <a href={m.source_url || "#"} target="_blank" rel="noopener noreferrer"
              className="mt-1 flex items-center gap-1 truncate" style={{ color: "var(--kai-hud)" }}>
              <ExternalLink size={11} /> <span className="truncate">{m.page_title || m.source_url}</span>
            </a>
          )}
          {m.kind === "web" && (
            <button onClick={() => setDetail(m.face_id)} className="mt-1 rounded border border-line px-2 py-0.5 hover:bg-panel"
              style={{ color: "var(--kai-hud)" }}>
              Open full web details
            </button>
          )}
          {(m.caption || m.context) && <div className="mt-1 text-muted">{m.caption || m.context}</div>}
          {(m.sex || m.age) && <div className="kai-metadata mt-1">{[m.sex, m.age ? `~${m.age}y` : ""].filter(Boolean).join(" · ")}</div>}
          <div className="mt-1 grid gap-0.5">
            {facts.filter(([, v]) => v.length).map(([k, v]) => (
              <div key={k}><span className="text-muted">{k}: </span>{v.slice(0, 8).join(", ")}</div>
            ))}
          </div>
        </div>
      </div>

      <div className="mt-3">
        {linked
          ? <PersonCard p={linked} />
          : <div className="kai-metadata">No national-ID record linked to this face — showing what the face index holds.</div>}
      </div>
    </div>
  );
}

/** Organised result of a people search: NID people (photo, record, family) first,
 *  then other face matches from the web index. Face matches are ≥ the server's 49% floor. */
export function PeopleResults({ r }: { r: PeopleSearchResult }) {
  const people = r.people || [];
  const faces = r.face_matches || [];
  const web = faces.length ? [] : (r.web_matches || []);
  const inSlider = new Set(faces.map((f) => f.linked_nid).filter(Boolean));
  const others = people.filter((p) => !inSlider.has(p.nid));
  if (people.length === 0 && web.length === 0 && faces.length === 0) {
    return <div className="kai-metadata my-2">No matches{r.notes?.length ? ` — ${r.notes.join(" ")}` : ""}.</div>;
  }
  return (
    <div className="my-2 grid gap-2 text-xs">
      {faces.length > 0 && <FaceSlider matches={faces} people={people} min={r.min_match_pct ?? 49} />}
      {others.map((p) => <PersonCard key={p.nid} p={p} />)}
      {web.length > 0 && (
        <div>
          <div className="kai-metadata mb-1">Other face matches ≥ {r.min_match_pct ?? 49}% ({web.length})</div>
          <div className="grid gap-1.5 sm:grid-cols-2">{web.map((m) => <WebCard key={m.face_id} m={m} />)}</div>
        </div>
      )}
      {r.notes && r.notes.length > 0 && <div className="kai-metadata">{r.notes.join(" ")}</div>}
      {r.disclaimer && <div className="kai-metadata italic">{r.disclaimer}</div>}
    </div>
  );
}
