import { Markdown } from "@/components/Markdown";
import type { Fact } from "@/lib/investigate";
import { CITATION_RE, isHttpUrl, splitCitations, stripMarkdownImages } from "@/lib/investigate";

function Cite({ id, fact }: { id: string; fact?: Fact }) {
  const cls = "mx-0.5 rounded border px-1 text-[10px]";
  if (!fact) return <span className={cls} style={{ borderColor: "var(--kai-border)", color: "var(--kai-muted)" }}>{id}</span>;
  const tip = `${fact.claim}: ${fact.value} (${fact.source}, ${fact.confidence}%)`;
  if (isHttpUrl(fact.source_ref)) {
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

export function AnalysisTab({ analysis, facts, notes, droppedCount = 0 }: {
  analysis: string | null;
  facts: Fact[];
  notes: string[];
  /** how many unsupported sentences the grounding check removed (never the sentences) */
  droppedCount?: number;
}) {
  const safeAnalysis = analysis ? stripMarkdownImages(analysis) : analysis;
  const byId = new Map(facts.map((f) => [f.id, f]));
  const hasMarkers = !!safeAnalysis && CITATION_RE.test(safeAnalysis);
  return (
    <div>
      {safeAnalysis ? (
        // Markers need inline chips, which Markdown cannot render, so marked text is plain pre-wrap.
        hasMarkers ? (
          <div className="whitespace-pre-wrap text-xs leading-relaxed">
            {splitCitations(safeAnalysis).map((p, i) =>
              p.type === "cite" ? <Cite key={i} id={p.value} fact={byId.get(p.value)} /> : <span key={i}>{p.value}</span>)}
          </div>
        ) : <Markdown>{safeAnalysis}</Markdown>
      ) : (
        <div className="kai-metadata">No analysis.</div>
      )}
      {droppedCount > 0 && (
        <div className="kai-metadata mt-2">
          {droppedCount === 1 ? "1 unsupported sentence was removed." : `${droppedCount} unsupported sentences were removed.`}
        </div>
      )}
      {notes.length > 0 && (
        <div className="mt-2 grid gap-0.5">
          {notes.map((n, i) => <div key={i} className="kai-metadata">{stripMarkdownImages(n)}</div>)}
        </div>
      )}
    </div>
  );
}
