import { useEffect, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Plus, Sparkles, Download } from "lucide-react";

import { api } from "@/lib/api";
import { investigationsApi } from "@/lib/investigations";
import type { EntityNode, EntityType, EvidenceItem, InvestigationDetail } from "@/types";

const ENTITY_TYPES: EntityType[] = [
  "face", "phone", "email", "username", "domain", "url", "image",
  "organization", "location", "document", "vehicle", "aircraft", "vessel",
];

type Tab = "entities" | "evidence";

export function Investigation() {
  const { id = "" } = useParams();
  const [detail, setDetail] = useState<InvestigationDetail | null>(null);
  const [tab, setTab] = useState<Tab>("entities");
  const [entities, setEntities] = useState<EntityNode[]>([]);
  const [evidence, setEvidence] = useState<EvidenceItem[]>([]);
  const [error, setError] = useState<string | null>(null);

  // new entity
  const [eType, setEType] = useState<EntityType>("phone");
  const [eValue, setEValue] = useState("");
  // new evidence
  const [evType, setEvType] = useState<EntityType>("url");
  const [evUrl, setEvUrl] = useState("");
  // AI analyst
  const [analysis, setAnalysis] = useState<string | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [analystError, setAnalystError] = useState<string | null>(null);

  async function runAnalyst() {
    setAnalyzing(true);
    setAnalystError(null);
    setAnalysis(null);
    try {
      const res = await api.post<{ summary: string; model: string }>(
        `/investigations/${id}/analyze`,
      );
      setAnalysis(res.summary);
    } catch (e: any) {
      setAnalystError(
        e?.detail === "ai_unavailable"
          ? "AI analyst is not configured (set OPENROUTER_API_KEY or OPENAI_API_KEY)."
          : "Analysis failed.",
      );
    } finally {
      setAnalyzing(false);
    }
  }

  async function load() {
    try {
      const [d, ents, evs] = await Promise.all([
        investigationsApi.get(id),
        investigationsApi.entities(id),
        investigationsApi.evidence(id),
      ]);
      setDetail(d);
      setEntities(ents);
      setEvidence(evs);
    } catch {
      setError("Failed to load investigation.");
    }
  }

  useEffect(() => {
    if (id) load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  async function addEntity(e: FormEvent) {
    e.preventDefault();
    if (!eValue.trim()) return;
    try {
      await investigationsApi.addEntity(id, { type: eType, value: eValue.trim() });
      setEValue("");
      await load();
    } catch {
      setError("Failed to add entity.");
    }
  }

  async function addEvidence(e: FormEvent) {
    e.preventDefault();
    if (!evUrl.trim()) return;
    try {
      await investigationsApi.addEvidence(id, { type: evType, source_url: evUrl.trim() });
      setEvUrl("");
      await load();
    } catch {
      setError("Failed to add evidence (source URL must be http/https).");
    }
  }

  async function exportCase(fmt: "json" | "csv") {
    const base = import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000";
    const token = localStorage.getItem("kai.token");
    const resp = await fetch(`${base}/investigations/${id}/export?format=${fmt}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!resp.ok) return;
    const blob = await resp.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${detail?.code ?? "case"}.${fmt === "json" ? "json" : "csv"}`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  if (!detail) {
    return <div className="kai-metadata">{error ?? "Loading…"}</div>;
  }

  return (
    <div>
      <Link to="/investigations" className="kai-metadata mb-4 inline-flex items-center gap-1 hover:text-ink">
        <ArrowLeft size={13} /> All investigations
      </Link>

      <div className="mb-5 flex items-center justify-between">
        <div>
          <div className="kai-metadata">{detail.code}</div>
          <h1 className="text-lg font-semibold">{detail.name}</h1>
        </div>
        <div className="flex items-center gap-3">
          <button onClick={() => exportCase("json")} className="kai-metadata flex items-center gap-1 rounded border border-line px-2 py-1 hover:text-ink">
            <Download size={12} /> JSON
          </button>
          <button onClick={() => exportCase("csv")} className="kai-metadata flex items-center gap-1 rounded border border-line px-2 py-1 hover:text-ink">
            <Download size={12} /> CSV
          </button>
          <span
            className="kai-metadata uppercase"
            style={{ color: detail.status === "open" ? "var(--kai-verified)" : "var(--kai-muted)" }}
          >
            {detail.status}
          </span>
        </div>
      </div>

      {error && <div className="mb-4 text-sm" style={{ color: "var(--kai-accent)" }}>{error}</div>}

      <div className="mb-4 flex gap-2 border-b border-line">
        {(["entities", "evidence"] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-3 py-2 text-sm capitalize ${
              tab === t ? "border-b-2 text-ink" : "text-muted"
            }`}
            style={tab === t ? { borderColor: "var(--kai-accent)" } : undefined}
          >
            {t} ({t === "entities" ? detail.entity_count : detail.evidence_count})
          </button>
        ))}
      </div>

      {tab === "entities" && (
        <div>
          <form onSubmit={addEntity} className="mb-4 flex gap-2">
            <select
              value={eType}
              onChange={(e) => setEType(e.target.value as EntityType)}
              className="rounded-md border border-line bg-panel px-2 py-2 text-sm"
            >
              {ENTITY_TYPES.map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
            <input
              value={eValue}
              onChange={(e) => setEValue(e.target.value)}
              placeholder="value (e.g. +250788123456)"
              className="flex-1 rounded-md border border-line bg-panel px-3 py-2 text-sm outline-none focus:border-muted"
            />
            <button className="flex items-center gap-1 rounded-md border border-line bg-panel px-3 py-2 text-sm hover:bg-panel-2">
              <Plus size={14} /> Add
            </button>
          </form>
          <div className="space-y-2">
            {entities.map((en) => (
              <div key={en.id} className="flex items-center justify-between rounded-md border border-line bg-panel px-3 py-2">
                <span className="text-sm">{en.value}</span>
                <span className="kai-metadata uppercase">{en.type}</span>
              </div>
            ))}
            {entities.length === 0 && <div className="text-sm text-muted">No entities yet.</div>}
          </div>
        </div>
      )}

      {tab === "evidence" && (
        <div>
          <form onSubmit={addEvidence} className="mb-4 flex gap-2">
            <select
              value={evType}
              onChange={(e) => setEvType(e.target.value as EntityType)}
              className="rounded-md border border-line bg-panel px-2 py-2 text-sm"
            >
              {ENTITY_TYPES.map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
            <input
              value={evUrl}
              onChange={(e) => setEvUrl(e.target.value)}
              placeholder="source URL (https://…)"
              className="flex-1 rounded-md border border-line bg-panel px-3 py-2 text-sm outline-none focus:border-muted"
            />
            <button className="flex items-center gap-1 rounded-md border border-line bg-panel px-3 py-2 text-sm hover:bg-panel-2">
              <Plus size={14} /> Add
            </button>
          </form>
          <div className="space-y-2">
            {evidence.map((ev) => (
              <div key={ev.id} className="rounded-md border border-line bg-panel px-3 py-2">
                <div className="flex items-center justify-between">
                  <span className="kai-metadata uppercase">{ev.type}</span>
                  {ev.band && (
                    <span className="kai-metadata" style={{ color: "var(--kai-warn)" }}>
                      {ev.band.replace(/_/g, " ")}
                    </span>
                  )}
                </div>
                <a href={ev.source_url} target="_blank" rel="noreferrer" className="block truncate text-sm text-ink hover:underline">
                  {ev.source_url}
                </a>
                <div className="kai-metadata mt-1">collected {new Date(ev.collected_at).toLocaleString()}</div>
              </div>
            ))}
            {evidence.length === 0 && <div className="text-sm text-muted">No evidence yet.</div>}
          </div>
        </div>
      )}

      {/* AI analyst */}
      <div className="mt-8 rounded-lg border border-line bg-panel p-4">
        <div className="mb-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Sparkles size={16} className="text-muted" />
            <span className="kai-metadata uppercase">AI Analyst</span>
          </div>
          <button
            onClick={runAnalyst}
            disabled={analyzing}
            className="rounded-md border border-line px-3 py-1.5 text-xs hover:bg-panel-2 disabled:opacity-50"
          >
            {analyzing ? "Analyzing…" : "Summarize evidence"}
          </button>
        </div>
        {analystError && <div className="text-sm" style={{ color: "var(--kai-accent)" }}>{analystError}</div>}
        {analysis && (
          <div className="whitespace-pre-wrap text-sm leading-relaxed text-ink">{analysis}</div>
        )}
        {!analysis && !analystError && (
          <div className="text-sm text-muted">
            Generate a grounded summary of this investigation's evidence. Every claim is traceable to a source.
          </div>
        )}
      </div>
    </div>
  );
}
