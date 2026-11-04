import { useEffect, useRef, useState } from "react";
import { ChevronRight, Search } from "lucide-react";
import { Spinner } from "@/components/Async";
import { AnalysisTab } from "@/components/chat/AnalysisTab";
import { PersonSummary, RelationsPanel, WebSection } from "@/components/chat/RelationsPanel";
import type {
  Fact, InvestigateBody, InvestigateResult, OneHopResult, PersonRef, Relations, WebFinding, WebOnlyResult,
} from "@/lib/investigate";
import { investigateStream, personOneHop } from "@/lib/investigate";

interface View {
  key: string;
  label: string;
  person: PersonRef | null;
  relations: Relations | null;
  facts: Fact[];
  notes: string[];
  analysis: string | null;
  droppedCount: number;
  findings: WebFinding[];
  spouseCandidates: string[];
  collision: boolean;
  /** a name lookup matched several people: the operator picks one */
  candidates?: PersonRef[];
  candidateCount?: number;
  webOnly?: WebOnlyResult;
  noMatch?: boolean;
}

type AgentState = "running" | "done" | "error";

/** The request to repeat on Retry: the one that failed, not the root person. */
type LastRequest =
  | { kind: "run"; body: InvestigateBody; replace: boolean }
  | { kind: "open"; nid: string | null; name: string };

function fromResult(r: InvestigateResult, key: string, label: string): View {
  const v: View = {
    key, label, person: r.person, relations: r.relations, facts: r.facts, notes: r.notes,
    analysis: r.analysis, droppedCount: r.analysis_dropped_count ?? 0,
    findings: r.web_findings ?? [], spouseCandidates: r.spouse_candidates ?? [],
    collision: !!r.name_collision_warning,
  };
  if (r.ambiguous && r.people.length > 1) {
    v.candidates = r.people.slice(0, 5);
    v.candidateCount = r.candidate_count ?? r.people.length;
  }
  return v;
}

function fromOneHop(r: OneHopResult | WebOnlyResult, key: string, label: string): View {
  if (r.person === null) {
    return {
      key, label: r.name, person: null, relations: null, facts: r.facts, notes: r.notes, analysis: null,
      droppedCount: 0, findings: r.findings ?? [], spouseCandidates: r.spouse_candidates ?? [],
      collision: !!r.name_collision_warning, webOnly: r,
    };
  }
  return {
    key, label: r.person.name || label, person: r.person, relations: r.relations, facts: r.facts,
    notes: r.notes, analysis: null, droppedCount: 0, findings: [], spouseCandidates: [], collision: false,
  };
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
  const streamAbort = useRef<AbortController | null>(null);
  const hopAbort = useRef<AbortController | null>(null);
  const token = useRef(0); // bumped by every run / open / breadcrumb jump; older responses are discarded
  const mounted = useRef(true);
  const lastReq = useRef<LastRequest | null>(null);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      streamAbort.current?.abort();
      hopAbort.current?.abort();
    };
  }, []);

  /** Invalidate anything in flight and return the new token. */
  const supersede = () => {
    hopAbort.current?.abort();
    hopAbort.current = null;
    setLoadingKey(null);
    return ++token.current;
  };

  const run = async (body: InvestigateBody, replace: boolean) => {
    lastReq.current = { kind: "run", body, replace };
    if (replace) setStack([]);
    streamAbort.current?.abort();
    const my = supersede();
    const live = () => mounted.current && token.current === my;
    const ac = new AbortController();
    streamAbort.current = ac;
    setRunning(true);
    setError(null);
    setNavErr(null);
    setAgents({});
    let got = false;
    try {
      await investigateStream(body, (e) => {
        if (!live()) return;
        if (e.event === "agent_start") setAgents((a) => ({ ...a, [e.data.agent]: "running" }));
        else if (e.event === "agent_done") setAgents((a) => ({ ...a, [e.data.agent]: "done" }));
        else if (e.event === "agent_error") setAgents((a) => ({ ...a, [e.data.agent]: "error" }));
        else if (e.event === "error") setError(e.data.detail);
        else if (e.event === "result") {
          got = true;
          const ambiguous = !!e.data.ambiguous && e.data.people.length > 1;
          // an ambiguous name result is keyed by the name and never cached under
          // the first namesake's NID: it is a chooser, not that person's view
          const key = ambiguous ? `name:${body.name}` : e.data.person?.nid ?? body.nid ?? `name:${body.name}`;
          const label = ambiguous ? body.name ?? name : e.data.person?.name ?? body.name ?? name;
          const v = fromResult(e.data, key, label);
          if (!e.data.person) v.noMatch = true;
          else if (!v.candidates) cache.current.set(v.key, v);
          setStack((s) => (replace ? [v] : [...s, v]));
          setTab("relations");
        }
      }, ac.signal);
      if (!got && live()) setError((cur) => cur ?? "no result");
    } catch (err: any) {
      if (live() && err?.name !== "AbortError") setError(err?.message || "failed to load");
    } finally {
      if (mounted.current && streamAbort.current === ac) setRunning(false);
    }
  };

  const open = async (targetNid: string | null, targetName: string) => {
    if (loadingKey) return;
    lastReq.current = { kind: "open", nid: targetNid, name: targetName };
    const key = targetNid ?? `web:${targetName}`;
    const my = supersede();
    setNavErr(null);
    setError(null); // a stale stream error's Retry must not retarget to this open
    const hit = cache.current.get(key);
    if (hit) {
      setStack((s) => [...s, hit]);
      return;
    }
    const ac = new AbortController();
    hopAbort.current = ac;
    setLoadingKey(key);
    try {
      const v = fromOneHop(await personOneHop(key, ac.signal), key, targetName);
      if (!mounted.current || token.current !== my) return;
      cache.current.set(key, v);
      setStack((s) => [...s, v]);
      setTab("relations");
    } catch (err: any) {
      if (mounted.current && token.current === my && err?.name !== "AbortError") {
        setNavErr(err?.message || "failed to load");
      }
    } finally {
      if (mounted.current && token.current === my) setLoadingKey(null);
    }
  };

  const jumpTo = (i: number) => {
    supersede();
    setNavErr(null);
    setStack((s) => s.slice(0, i + 1));
  };

  const retry = () => {
    const last = lastReq.current;
    if (!last) return;
    if (last.kind === "run") void run(last.body, last.replace);
    else void open(last.nid, last.name);
  };

  const current = stack[stack.length - 1];
  const started = running || stack.length > 0 || error !== null;
  const retryButton = (
    <button type="button" disabled={running || loadingKey !== null} onClick={retry}
      className="rounded border border-line px-2 py-0.5 text-xs hover:bg-panel disabled:opacity-40">
      Retry
    </button>
  );

  return (
    <div className="mt-3 border-t border-line pt-2">
      <div className="flex flex-wrap items-center gap-3">
        <button type="button" disabled={running} onClick={() => void run({ nid, web, analyse }, true)}
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
          {retryButton}
        </div>
      )}

      {started && current && (
        <div className="mt-2">
          <nav aria-label="Visited people" className="mb-2 flex flex-wrap items-center gap-1 kai-metadata">
            {stack.map((v, i) => (
              <span key={`${v.key}-${i}`} className="flex items-center gap-1">
                {i > 0 && <ChevronRight size={11} className="text-muted" />}
                {i < stack.length - 1
                  ? <button type="button" className="hover:underline" onClick={() => jumpTo(i)}>{v.label}</button>
                  : <span className="text-ink">{v.label}</span>}
              </span>
            ))}
          </nav>

          {loadingKey && <div className="mb-2"><Spinner size={12} label="Loading…" /></div>}
          {navErr && (
            <div className="mb-2 flex items-center gap-2 text-xs" style={{ color: "var(--kai-accent)" }}>
              <span>Could not load: {navErr}</span>
              {retryButton}
            </div>
          )}

          {current.webOnly ? (
            <div className="rounded border border-line bg-panel p-2">
              <div className="flex items-center gap-2">
                <span className="text-xs font-medium">{current.webOnly.name}</span>
                <span className="rounded border border-line px-1 text-[10px]" style={{ color: "var(--kai-warn)" }}>not in system</span>
                <button type="button" disabled={running}
                  className="rounded border border-line px-2 py-0.5 text-xs hover:bg-panel-2 disabled:opacity-40"
                  style={{ color: "var(--kai-hud)" }}
                  onClick={() => void run({ name: current.webOnly!.name, web, analyse }, false)}>
                  look up in system
                </button>
              </div>
              <WebSection facts={current.facts} findings={current.findings}
                spouseCandidates={current.spouseCandidates} collision={current.collision}
                onOpen={open} disabled={loadingKey !== null} />
              {current.notes.map((n, i) => <div key={i} className="kai-metadata mt-1">{n}</div>)}
            </div>
          ) : current.noMatch ? (
            <div className="kai-metadata">No match found in the system.</div>
          ) : current.candidates ? (
            <div className="rounded border border-line bg-panel p-2">
              <div className="kai-metadata mb-1">
                Several people match this name
                {(current.candidateCount ?? 0) > current.candidates.length
                  ? ` (showing ${current.candidates.length} of ${current.candidateCount})` : ""}
              </div>
              <div className="grid gap-1.5 sm:grid-cols-2">
                {current.candidates.map((c, i) => (
                  <button key={`${c.nid}-${i}`} type="button" disabled={loadingKey !== null}
                    className="rounded border border-line bg-panel p-1.5 text-left hover:bg-panel-2 disabled:opacity-40"
                    title="Open this person" onClick={() => void open(c.nid, c.name)}>
                    <div className="truncate text-xs font-medium">{c.name || c.nid}</div>
                    <div className="kai-metadata truncate">{c.nid}</div>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <>
              {current.person && <PersonSummary person={current.person} />}
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
              {tab === "relations" ? (
                <>
                  <RelationsPanel key={current.key} relations={current.relations} onOpen={open} disabled={loadingKey !== null} />
                  <WebSection facts={current.facts} findings={current.findings} nodes={current.relations?.nodes}
                    spouseCandidates={current.spouseCandidates} collision={current.collision}
                    onOpen={open} disabled={loadingKey !== null} />
                </>
              ) : (
                <AnalysisTab analysis={current.analysis} facts={current.facts} notes={current.notes}
                  droppedCount={current.droppedCount} />
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
