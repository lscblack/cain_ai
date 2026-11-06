import { useEffect, useState } from "react";
import { X, Globe, ExternalLink, Image as ImageIcon, Users, FileText, IdCard } from "lucide-react";
import { AuthImg } from "@/components/AuthImg";
import { webFaceApi, type WebFaceDetail } from "@/lib/enrich";

function pct(n: number) {
  return n >= 70 ? "var(--kai-verified)" : n >= 55 ? "var(--kai-warn)" : "var(--kai-muted)";
}

function Crop({ url, size }: { url?: string | null; size: number }) {
  const s = { width: size, height: size };
  return url
    ? <AuthImg path={url} className="shrink-0 rounded border border-line object-cover" style={s} />
    : <div className="shrink-0 rounded border border-line" style={{ ...s, background: "var(--kai-panel-2)" }} />;
}

function Rows({ rows }: { rows: [string, unknown][] }) {
  const shown = rows.filter(([, v]) => Array.isArray(v) ? v.length > 0 : v !== null && v !== undefined && v !== "");
  if (!shown.length) return null;
  return (
    <div className="grid gap-0.5 text-[12px]">
      {shown.map(([k, v]) => (
        <div key={k}><span className="text-muted">{k}: </span>{Array.isArray(v) ? v.join(", ") : String(v)}</div>
      ))}
    </div>
  );
}

function Section({ icon: Icon, title, children }: { icon: typeof Globe; title: string; children: React.ReactNode }) {
  return (
    <div className="mt-4">
      <div className="mb-1.5 flex items-center gap-1.5">
        <Icon size={13} style={{ color: "var(--kai-hud)" }} />
        <span className="hud-mono text-[11px] uppercase" style={{ color: "var(--kai-hud)" }}>{title}</span>
      </div>
      {children}
    </div>
  );
}

/** Full-screen view of one web face and everything the crawler collected around it.
 *  Clicking another appearance switches the main view to that face. */
export function WebFaceModal({ faceId, onClose }: { faceId: string; onClose: () => void }) {
  const [id, setId] = useState(faceId);
  const [d, setD] = useState<WebFaceDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    setD(null); setErr(null);
    webFaceApi.detail(id).then((r) => live && setD(r)).catch((e) => live && setErr(e?.message || "failed to load"));
    return () => { live = false; };
  }, [id]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const f = d?.face;
  const meta = d?.page?.meta || {};
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" onClick={onClose}>
      <div role="dialog" aria-modal="true" aria-label="Web face details"
        className="flex max-h-[90vh] w-full max-w-4xl flex-col rounded-lg border border-line bg-panel shadow-xl"
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-line px-4 py-3">
          <div className="flex min-w-0 items-center gap-2">
            <Globe size={16} style={{ color: "var(--kai-hud)" }} />
            <span className="hud-mono truncate text-sm" style={{ color: "var(--kai-hud)" }}>
              {f?.page_title || f?.source_url || "Web face"}
            </span>
          </div>
          <button onClick={onClose} aria-label="Close" className="text-muted hover:text-ink"><X size={16} /></button>
        </div>

        <div className="overflow-auto p-4 text-xs">
          {err && <div style={{ color: "var(--kai-accent)" }}>Could not load details: {err}</div>}
          {!d && !err && <div className="kai-metadata">Loading everything crawled for this face…</div>}
          {d && f && (
            <>
              {/* main: the face + the original crawled image */}
              <div className="flex flex-wrap gap-4">
                <Crop url={f.crop_url} size={180} />
                {f.image_url && (
                  <a href={f.image_url} target="_blank" rel="noopener noreferrer" title="Open the original image">
                    <img src={f.image_url} alt={f.alt || "original crawled image"} referrerPolicy="no-referrer"
                      className="max-h-[180px] max-w-[320px] rounded border border-line object-contain" />
                  </a>
                )}
                <div className="min-w-[220px] flex-1">
                  <div className="text-base font-semibold">{f.names[0] || "Unnamed face"}</div>
                  {f.source_url && (
                    <a href={f.source_url} target="_blank" rel="noopener noreferrer"
                      className="mt-1 flex items-center gap-1 break-all" style={{ color: "var(--kai-hud)" }}>
                      <ExternalLink size={12} className="shrink-0" /> {f.source_url}
                    </a>
                  )}
                  <div className="mt-2">
                    <Rows rows={[
                      ["Names", f.names], ["Titles", f.titles], ["Organisations", f.orgs],
                      ["Phones", f.phones], ["Emails", f.emails], ["Usernames", f.usernames],
                      ["Locations", f.locations], ["Caption", f.caption], ["Alt text", f.alt],
                      ["Context", f.context],
                      ["Estimated", [f.sex, f.age ? `~${f.age} years` : null].filter(Boolean).join(", ")],
                      ["Original image", f.image_url],
                      ["Image size", f.image_size ? `${f.image_size[0]} × ${f.image_size[1]}` : null],
                      ["Face quality", `${Math.round(f.quality * 100)}% (detector ${Math.round(f.det_score * 100)}%)`],
                      ["Indexed", f.detected_at?.slice(0, 19).replace("T", " ")],
                    ]} />
                  </div>
                </div>
              </div>

              {d.page && (
                <Section icon={FileText} title="Page it was crawled from">
                  <div className="rounded border border-line bg-panel-2 p-3">
                    <div className="font-semibold">{d.page.title}</div>
                    {d.page.description && <p className="mt-1 whitespace-pre-wrap leading-relaxed">{d.page.description}</p>}
                    <div className="mt-2">
                      <Rows rows={[
                        ["Emails on page", d.page.emails], ["Phones on page", d.page.phones],
                        ["Usernames on page", d.page.usernames],
                        ...Object.entries(meta).map(([k, v]) => [k.charAt(0).toUpperCase() + k.slice(1), v] as [string, unknown]),
                        ["Images / faces on page", `${d.page.images_found} / ${d.page.faces_found}`],
                        ["HTTP status", d.page.http_status],
                        ["Last crawled", d.page.last_crawled_at?.slice(0, 19).replace("T", " ")],
                        ["Last changed", d.page.last_changed_at?.slice(0, 19).replace("T", " ")],
                      ]} />
                    </div>
                  </div>
                </Section>
              )}

              {d.source && (
                <Section icon={Globe} title="Crawl source">
                  <Rows rows={[["Source", d.source.name], ["Domain", d.source.domain], ["Base URL", d.source.base_url],
                    ["Category", d.source.category],
                    ["Source last crawled", d.source.last_crawled_at?.slice(0, 19).replace("T", " ")]]} />
                </Section>
              )}

              {d.appearances.length > 0 && (
                <Section icon={ImageIcon} title={`Same person elsewhere in the index (${d.appearances.length})`}>
                  <div className="grid gap-1.5 sm:grid-cols-2">
                    {d.appearances.map((a) => (
                      <button key={a.face_id} onClick={() => a.kind === "web" && setId(a.face_id)}
                        disabled={a.kind !== "web"}
                        className="flex items-center gap-2 rounded border border-line bg-panel-2 p-1.5 text-left enabled:hover:bg-panel"
                        title={a.kind === "web" ? "Show this face as the main view" : "ID photo"}>
                        <Crop url={a.crop_url} size={48} />
                        <div className="min-w-0 flex-1">
                          <div className="truncate text-[12px]">{a.names[0] || a.page_title || "match"}</div>
                          <div className="kai-metadata flex items-center gap-1 truncate">
                            {a.kind === "nid" ? <><IdCard size={10} /> ID photo {a.nid}</> : (a.page_title || a.source_url)}
                          </div>
                        </div>
                        <span className="hud-mono text-xs" style={{ color: pct(a.match_pct) }}>{a.match_pct}%</span>
                      </button>
                    ))}
                  </div>
                </Section>
              )}

              {d.same_page_faces.length > 0 && (
                <Section icon={Users} title={`Other faces on the same page (${d.same_page_faces.length})`}>
                  <div className="flex flex-wrap gap-2">
                    {d.same_page_faces.map((s) => (
                      <button key={s.face_id} onClick={() => setId(s.face_id)} title={s.names[0] || "face"}>
                        <Crop url={s.crop_url} size={56} />
                      </button>
                    ))}
                  </div>
                </Section>
              )}

              {d.site_pages.length > 0 && (
                <Section icon={FileText} title={`Other pages crawled on ${d.source?.domain} (${d.site_pages.length})`}>
                  <ul className="grid gap-1">
                    {d.site_pages.map((p) => (
                      <li key={p.url}>
                        <a href={p.url} target="_blank" rel="noopener noreferrer" className="hover:underline" style={{ color: "var(--kai-hud)" }}>
                          {p.title || p.url}
                        </a>
                        <span className="kai-metadata"> · {p.faces_found} face{p.faces_found === 1 ? "" : "s"}
                          {[...p.phones, ...p.emails].length ? ` · ${[...p.phones, ...p.emails].slice(0, 3).join(", ")}` : ""}</span>
                      </li>
                    ))}
                  </ul>
                </Section>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
