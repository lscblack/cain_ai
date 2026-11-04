import { useRef, useState } from "react";
import { ChevronRight, Search } from "lucide-react";
import { Spinner } from "@/components/Async";
import { AnalysisTab } from "@/components/chat/AnalysisTab";
import { RelationsPanel } from "@/components/chat/RelationsPanel";
import type { Fact, InvestigateResult, OneHopResult, Relations, WebOnlyResult } from "@/lib/investigate";
import { investigateStream, personOneHop } from "@/lib/investigate";

interface View {
  key: string;
  label: string;
  relations: Relations | null;
  facts: Fact[];
  notes: string[];
  analysis: string | null;
  dropped?: string[];
  webOnly?: WebOnlyResult;
}

type AgentState = "running" | "done" | "error";

function fromResult(r: InvestigateResult, key: string, label: string): View {
  return { key, label, relations: r.relations, facts: r.facts, notes: r.notes, analysis: r.analysis, dropped: r.dropped };
}

function fromOneHop(r: OneHopResult | WebOnlyResult, key: string, label: string): View {
  if (r.person === null) {
    return { key, label: r.name, relations: null, facts: r.facts, notes: r.notes, analysis: null, webOnly: r };
  }
  return { key, label: r.person.name || label, relations: r.relations, facts: r.facts, notes: r.notes, analysis: null };
}

const TAB = "border-b-2 hud-mono px-2 py-1 text-xs";

export function InvestigatePanel({ nid, name }: { nid: string; name: string }) {
  const [web, setWeb] = useState(false);
  const [analyse, setAnalyse] = useState(false);
  const [running, setRunning] = useState(false);
  const [agents, setAgents] = useState<Record<string, AgentState>>({});
  const [error, setError] = useState<string | null>(null);
  const [stack, setStack] = useState<View[]>([]);
  const [tab, setTab] = useState<"relations" | "analysis">("relations");
  const [loadingKey, setLoadingKey] = useState<string | null>(null);
  const [navErr, setNavErr] = useState<string | null>(null);
  const cache = useRef(new Map<string, View>());
  const abort = useRef<AbortController | null>(null);

  const run = async (body: { nid?: string; name?: string }, replace: boolean) => {
    abort.current?.abort();
    const ac = new AbortController();
    abort.current = ac;
    setRunning(true);
    setError(null);
    setAgents({});
    let got = false;
    try {
      await investigateStream({ ...body, web, analyse }, (e) => {
        if (e.event === "agent_start") setAgents((a) => ({ ...a, [e.data.agent]: "running" }));
        else if (e.event === "agent_done") setAgents((a) => ({ ...a, [e.data.agent]: "done" }));
        else if (e.event === "agent_error") setAgents((a) => ({ ...a, [e.data.agent]: "error" }));
        else if (e.event === "error") setError(e.data.detail);
        else if (e.event === "result") {
          got = true;
          const v = fromResult(e.data, e.data.person?.nid ?? body.nid ?? `name:${body.name}`, e.data.person?.name ?? body.name ?? name);
          if (v.key && e.data.person) cache.current.set(v.key, v);
          setStack((s) => (replace ? [v] : [...s, v]));
          setTab("relations");
          if (!e.data.person) setError(null);
        }
      }, ac.signal);
      if (!got) setError((cur) => cur ?? "no result");
    } catch (err: any) {
      if (err?.name !== "AbortError") setError(err?.message || "failed to load");
    } finally {
      if (abort.current === ac) setRunning(false);
    }
  };

  const open = async (targetNid: string | null, targetName: string) => {
    const key = targetNid ?? `web:${targetName}`;
    setNavErr(null);
    const hit = cache.current.get(key);
    if (hit) {
      setStack((s) => [...s, hit]);
      return;
    }
    setLoadingKey(key);
    try {
      const v = fromOneHop(await personOneHop(key), key, targetName);
      cache.current.set(key, v);
      setStack((s) => [...s, v]);
      setTab("relations");
    } catch (err: any) {
      setNavErr(err?.message || "failed to load");
    } finally {
      setLoadingKey(null);
    }
  };

  const current = stack[stack.length - 1];
  const started = running || stack.length > 0 || error !== null;

  return (
    <div className="mt-3 border-t border-line pt-2">
      <div className="flex flex-wrap items-center gap-3">
        <button type="button" disabled={running} onClick={() => { setStack([]); void run({ nid }, true); }}
          className="flex items-center gap-1 rounded border border-line px-2 py-1 text-xs hover:bg-panel disabled:opacity-40"
          style={{ color: "var(--kai-hud)" }} title={`Investigate ${name}`}>
          <Search size={12} /> Investigate
        </button>
        <label className="flex items-center gap-2 text-[11px] text-muted">
          <input type="checkbox" checked={web} onChange={(e) => setWeb(e.target.checked)} />
          Search the web
        </label>
        <label className="flex items-center gap-2 text-[11px] text-muted">
          <input type="checkbox" checked={analyse} onChange={(e) => setAnalyse(e.target.checked)} />
          Write analysis
        </label>
      </div>

      {Object.keys(agents).length > 0 && (
        <div className="mt-2 flex flex-wrap items-center gap-3">
          {Object.entries(agents).map(([a, st]) => (
            <span key={a} className="kai-metadata flex items-center gap-1">
              {a}
              {st === "running" ? <Spinner size={12} /> : st === "done" ? "✓" : (
                <span style={{ color: "var(--kai-accent)" }}>failed</span>
              )}
            </span>
          ))}
        </div>
      )}

      {error && (
        <div className="mt-2 flex items-center gap-2 text-xs" style={{ color: "var(--kai-accent)" }}>
          <span>Could not load: {error}</span>
          <button type="button" onClick={() => { setStack([]); void run({ nid }, true); }}
            className="rounded border border-line px-2 py-0.5 text-xs hover:bg-panel">
            Retry
          </button>
        </div>
      )}

      {started && current && (
        <div className="mt-2">
          <nav aria-label="Visited people" className="mb-2 flex flex-wrap items-center gap-1 kai-metadata">
            {stack.map((v, i) => (
              <span key={`${v.key}-${i}`} className="flex items-center gap-1">
                {i > 0 && <ChevronRight size={11} className="text-muted" />}
                {i < stack.length - 1
                  ? <button type="button" className="hover:underline" onClick={() => setStack((s) => s.slice(0, i + 1))}>{v.label}</button>
                  : <span className="text-ink">{v.label}</span>}
              </span>
            ))}
          </nav>

          {loadingKey && <div className="mb-2"><Spinner size={12} label="Loading…" /></div>}
          {navErr && (
            <div className="mb-2 text-xs" style={{ color: "var(--kai-accent)" }}>Could not load: {navErr}</div>
          )}

          {current.webOnly ? (
            <div className="rounded border border-line bg-panel p-2">
              <div className="flex items-center gap-2">
                <span className="text-xs font-medium">{current.webOnly.name}</span>
                <span className="rounded border border-line px-1 text-[10px]" style={{ color: "var(--kai-warn)" }}>not in system</span>
                <button type="button" disabled={running}
                  className="rounded border border-line px-2 py-0.5 text-xs hover:bg-panel-2 disabled:opacity-40"
                  style={{ color: "var(--kai-hud)" }}
                  onClick={() => void run({ name: current.webOnly!.name }, false)}>
                  look up in system
                </button>
              </div>
              {current.webOnly.spouse_candidates.length > 0 && (
                <div className="kai-metadata mt-1">Possible spouse: {current.webOnly.spouse_candidates.join(", ")}</div>
              )}
              {current.notes.map((n, i) => <div key={i} className="kai-metadata mt-1">{n}</div>)}
            </div>
          ) : (
            <>
              <div className="mb-2 flex gap-1">
                {(["relations", "analysis"] as const).map((t) => (
                  <button key={t} type="button" onClick={() => setTab(t)} className={TAB}
                    style={{
                      borderColor: tab === t ? "var(--kai-hud)" : "transparent",
                      color: tab === t ? "var(--kai-hud)" : "var(--kai-muted)",
                    }}>
                    {t === "relations" ? "Relations" : "Analysis"}
                  </button>
                ))}
              </div>
              {tab === "relations"
                ? <RelationsPanel key={current.key} relations={current.relations} onOpen={open} />
                : <AnalysisTab analysis={current.analysis} facts={current.facts} notes={current.notes} dropped={current.dropped} />}
            </>
          )}
        </div>
      )}
    </div>
  );
}
