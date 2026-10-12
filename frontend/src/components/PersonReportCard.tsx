import { AtSign, Briefcase, ExternalLink, MapPin, Phone, User2 } from "lucide-react";

import { AuthImg } from "@/components/AuthImg";

export interface ReportMatch {
  face_id: string;
  similarity_pct?: number;
  band?: string;
  crop_url?: string | null;
  names?: string[];
  age?: number | null;
  sex?: string | null;
  description?: string | null;
  caption?: string | null;
  page_title?: string | null;
  source_url?: string | null;
  image_url?: string | null;
  phones?: string[];
  emails?: string[];
  usernames?: string[];
  titles?: string[];
  orgs?: string[];
  locations?: string[];
}

const BAND_LABEL: Record<string, string> = {
  potential_match: "POTENTIAL MATCH",
  strong_similarity: "STRONG SIMILARITY",
  possible_association: "POSSIBLE ASSOCIATION",
  no_match: "NO MATCH",
};
const BAND_COLOR: Record<string, string> = {
  potential_match: "var(--kai-accent)",
  strong_similarity: "var(--kai-warn)",
  possible_association: "var(--kai-muted)",
  no_match: "var(--kai-muted)",
};

function Field({
  icon,
  label,
  values,
}: {
  icon: React.ReactNode;
  label: string;
  values: string[];
}) {
  if (!values.length) return null;
  return (
    <div className="flex gap-2">
      <span className="mt-0.5 shrink-0 text-muted">{icon}</span>
      <div className="min-w-0">
        <div className="kai-metadata uppercase">{label}</div>
        <div className="flex flex-wrap gap-x-3 gap-y-0.5">
          {values.map((v, i) => (
            <span key={i} className="truncate text-sm">
              {v}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

/** A per-result "dossier" card: matched face image beside the person's
 *  known attributes (name, age, job, bio, contacts, socials, sources).
 *  Matches are potential leads — never a confirmed identity. */
export function PersonReportCard({
  m,
  onOpenFrame,
}: {
  m: ReportMatch;
  onOpenFrame?: (m: ReportMatch) => void;
}) {
  const band = m.band ?? "no_match";
  const name = m.names?.[0] ?? m.page_title ?? "Unknown subject";
  const aliases = (m.names ?? []).slice(1, 6);
  const job = [m.titles?.[0], m.orgs?.[0]].filter(Boolean).join(" · ");
  const bio = m.description || m.caption || null;

  return (
    <div
      className="overflow-hidden rounded-lg border bg-panel"
      style={{ borderColor: "var(--kai-border)" }}
    >
      {/* header band */}
      <div
        className="flex items-center justify-between border-b px-3 py-1.5"
        style={{ borderColor: "var(--kai-border)", background: "var(--kai-panel-2)" }}
      >
        <span className="font-mono text-xs" style={{ color: "var(--kai-muted)" }}>
          DOSSIER · {m.face_id.slice(0, 8)}
        </span>
        <span className="flex items-center gap-2">
          {m.similarity_pct != null && (
            <span className="font-mono text-sm">{m.similarity_pct}%</span>
          )}
          <span className="kai-metadata" style={{ color: BAND_COLOR[band] }}>
            {BAND_LABEL[band] ?? band}
          </span>
        </span>
      </div>

      <div className="flex gap-3 p-3">
        {/* matched face */}
        <div className="shrink-0">
          <div
            className="h-32 w-32 overflow-hidden rounded border"
            style={{ borderColor: BAND_COLOR[band] }}
          >
            {m.crop_url ? (
              <AuthImg path={m.crop_url} className="h-full w-full object-cover" />
            ) : (
              <div className="flex h-full w-full items-center justify-center bg-panel-2 text-muted">
                <User2 size={28} />
              </div>
            )}
          </div>
        </div>

        {/* attributes */}
        <div className="min-w-0 flex-1 space-y-2">
          <div>
            <div className="truncate text-base font-semibold">{name}</div>
            <div className="kai-metadata mt-0.5">
              {[m.sex, (m.age ?? 0) > 0 ? `~${m.age}y` : null].filter(Boolean).join(" · ") ||
                "age/sex n/a"}
            </div>
          </div>

          {aliases.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {aliases.map((a) => (
                <span
                  key={a}
                  className="rounded border px-1.5 py-0.5 text-xs"
                  style={{ borderColor: "var(--kai-border)", color: "var(--kai-warn)" }}
                >
                  {a}
                </span>
              ))}
            </div>
          )}

          {job && <Field icon={<Briefcase size={14} />} label="Job / Title" values={[job]} />}
          <Field icon={<MapPin size={14} />} label="Location" values={m.locations ?? []} />

          {bio && (
            <div
              className="border-l-2 px-2 py-1 font-mono text-[11px] leading-relaxed"
              style={{
                borderColor: "var(--kai-accent)",
                background: "var(--kai-panel-2)",
                color: "var(--kai-muted)",
              }}
            >
              {bio}
            </div>
          )}

          <Field icon={<AtSign size={14} />} label="Emails" values={m.emails ?? []} />
          <Field icon={<Phone size={14} />} label="Phones" values={m.phones ?? []} />
          <Field icon={<User2 size={14} />} label="Social / usernames" values={m.usernames ?? []} />

          {m.source_url && (
            <div className="border-t pt-2" style={{ borderColor: "var(--kai-border)" }}>
              <div className="kai-metadata uppercase">Sources</div>
              <a
                href={m.source_url}
                target="_blank"
                rel="noreferrer"
                title={m.source_url}
                className="kai-metadata block truncate hover:text-ink"
              >
                {m.page_title ?? m.source_url}
              </a>
              <div className="mt-2 flex flex-wrap gap-2">
                {onOpenFrame && (
                  <button
                    onClick={() => onOpenFrame(m)}
                    className="rounded border px-2 py-1 text-xs hover:bg-panel-2"
                    style={{ borderColor: "var(--kai-border)" }}
                  >
                    Open in frame
                  </button>
                )}
                <a
                  href={m.source_url}
                  target="_blank"
                  rel="noreferrer"
                  className="flex items-center gap-1 rounded border px-2 py-1 text-xs hover:bg-panel-2"
                  style={{ borderColor: "var(--kai-border)" }}
                >
                  Read more <ExternalLink size={11} />
                </a>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
