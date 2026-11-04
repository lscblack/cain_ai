import { Markdown } from "@/components/Markdown";
import type { Fact } from "@/lib/investigate";
import { splitCitations } from "@/lib/investigate";

const isUrl = (s: string) => /^https?:\/\//i.test(s);

function Cite({ id, fact }: { id: string; fact?: Fact }) {
  const cls = "mx-0.5 rounded border px-1 text-[10px]";
  if (!fact) return <span className={cls} style={{ borderColor: "var(--kai-border)", color: "var(--kai-muted)" }}>{id}</span>;
  const tip = `${fact.claim}: ${fact.value} (${fact.source}, ${fact.confidence}%)`;
  if (isUrl(fact.source_ref)) {
    return (
      <a href={fact.source_ref} target="_blank" rel="noopener noreferrer" title={tip}
        className={`${cls} hover:underline`} style={{ borderColor: "var(--kai-border)", color: "var(--kai-hud)" }}>
        {id}
      </a>
    );
  }
  return (
    <span className={cls} title={`${tip}${fact.source_ref ? ` · ${fact.source_ref}` : ""}`}
      style={{ borderColor: "var(--kai-border)", color: "var(--kai-muted)" }}>
      {id}
    </span>
  );
}

export function AnalysisTab({ analysis, facts, notes, dropped }: {
  analysis: string | null;
  facts: Fact[];
  notes: string[];
  dropped?: string[];
}) {
  const byId = new Map(facts.map((f) => [f.id, f]));
  const hasMarkers = !!analysis && /\[F\d+\]/.test(analysis);
  return (
    <div>
      {analysis ? (
        hasMarkers ? (
          <div className="whitespace-pre-wrap text-xs leading-relaxed">
            {splitCitations(analysis).map((p, i) =>
              p.type === "cite" ? <Cite key={i} id={p.value} fact={byId.get(p.value)} /> : <span key={i}>{p.value}</span>)}
          </div>
        ) : <Markdown>{analysis}</Markdown>
      ) : (
        <div className="kai-metadata">No analysis.</div>
      )}
      {dropped && dropped.length > 0 && (
        <div className="kai-metadata mt-2">{dropped.length} unsupported sentences dropped</div>
      )}
      {notes.length > 0 && (
        <div className="mt-2 grid gap-0.5">
          {notes.map((n, i) => <div key={i} className="kai-metadata">{n}</div>)}
        </div>
      )}
    </div>
  );
}
