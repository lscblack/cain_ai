import { useEffect, useRef, useState } from "react";
import { Radar, Play, CheckCircle2, XCircle, Trash2, Sparkles } from "lucide-react";

import { api } from "@/lib/api";

interface Evaluation {
  domain: string;
  base_url: string;
  reachable: boolean;
  has_images: boolean;
  has_phones: boolean;
  has_emails: boolean;
  has_usernames: boolean;
  requires_auth: boolean;
  score: number;
  signals: string[];
  approved: boolean;
}
interface RunState {
  id: string;
  status: string;
  country: string | null;
  categories: string[];
  targets: string[];
  min_score: number;
  max_domains: number;
  candidates: number;
  already_known: number;
  new_domains: number;
  evaluated: number;
  approved: number;
  rejected: number;
  current: string | null;
  approved_list: Evaluation[];
  last?: Evaluation;
  progress: number;
  kind?: string;
}
interface Term {
  term: string;
  kind: string;
  count: number;
  local_hits?: number;
  pending?: boolean;
}

const COUNTRIES = ["rwanda", "kenya", "uganda", "tanzania", "nigeria", "ethiopia", "ghana", "south africa", "africa"];
const CATEGORIES = ["people", "phone", "username", "images", "business", "news"];
const TARGETS = ["phone", "email", "username", "images"];

function toggle(list: string[], v: string): string[] {
  return list.includes(v) ? list.filter((x) => x !== v) : [...list, v];
}

function normalize(v: string): string {
  return v.trim().toLowerCase();
}

export function Discover() {
  const [available, setAvailable] = useState<boolean | null>(null);
  const [country, setCountry] = useState("rwanda");
  const [categories, setCategories] = useState<string[]>(["people", "phone", "images"]);
  const [targets, setTargets] = useState<string[]>(["phone", "username", "images"]);
  const [minScore, setMinScore] = useState(60);
  const [maxDomains, setMaxDomains] = useState(500);
  const [autoCrawl, setAutoCrawl] = useState(true);
  const [catOptions, setCatOptions] = useState<string[]>(CATEGORIES);
  const [tgtOptions, setTgtOptions] = useState<string[]>(TARGETS);
  const [customCat, setCustomCat] = useState("");
  const [customTgt, setCustomTgt] = useState("");
  const [run, setRun] = useState<RunState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [terms, setTerms] = useState<Term[]>([]);
  const poll = useRef<ReturnType<typeof setInterval> | null>(null);

  async function loadStatus() {
    try {
      const s = await api.get<{ available: boolean }>("/discovery/status");
      setAvailable(s.available);
    } catch {
      setAvailable(false);
    }
  }
  async function loadTerms() {
    try {
      const r = await api.get<{ terms: Term[] }>("/discovery/terms");
      setTerms(r.terms || []);
    } catch {
      /* ignore */
    }
  }

  useEffect(() => {
    loadStatus();
    loadTerms();
    return () => {
      if (poll.current) clearInterval(poll.current);
    };
  }, []);

  async function start() {
    setError(null);
    try {
      const res = await api.post<{ id: string }>("/discovery/run", {
        country,
        categories,
        targets,
        min_score: minScore,
        max_domains: maxDomains,
        auto_crawl: autoCrawl,
      });
      if (poll.current) clearInterval(poll.current);
      poll.current = setInterval(() => pollRun(res.id), 1200);
      pollRun(res.id);
    } catch (e: any) {
      setError(e?.detail || "Discovery failed to start (SERPAPI_API_KEY set?).");
    }
  }

  async function pollRun(id: string) {
    try {
      const st = await api.get<RunState>(`/discovery/runs/${id}`);
      setRun(st);
      if (st.status === "done" && poll.current) {
        clearInterval(poll.current);
        poll.current = null;
        loadTerms();
      }
    } catch {
      /* transient */
    }
  }

  async function clearTerms() {
    if (!confirm("Clear the self-learning term queue?")) return;
    await api.del("/discovery/terms");
    loadTerms();
  }

  const running = run && run.status !== "done";

  return (
    <div className="w-11/12 max-w-[1700px] mx-auto space-y-6">
      <header className="flex items-center gap-3">
        <Radar className="text-accent" size={22} />
        <div>
          <h1 className="text-xl font-semibold tracking-wide">Source Discovery</h1>
          <p className="kai-metadata">Discover → qualify → crawl → monitor → rediscover</p>
        </div>
      </header>

      {available === false && (
        <div className="border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm text-amber-300">
          Discovery search is unavailable. Set <code>SERPAPI_API_KEY</code> in the backend env to enable live discovery.
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        {/* ── FORM ── */}
        <section className="border border-line bg-panel-2 p-5">
          <div className="mb-4 kai-metadata">DISCOVER NEW SOURCES</div>

          <label className="mb-3 block text-sm">
            <span className="mb-1 block text-muted uppercase tracking-wider text-xs">Region / Country</span>
            <select
              value={country}
              onChange={(e) => setCountry(e.target.value)}
              className="w-full border border-line bg-base px-3 py-2 text-ink"
            >
              {COUNTRIES.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </label>

          <div className="mb-3">
            <span className="mb-1 block text-muted uppercase tracking-wider text-xs">Categories</span>
            <div className="flex flex-wrap gap-2">
              {catOptions.map((c) => (
                <button
                  key={c}
                  onClick={() => setCategories((l) => toggle(l, c))}
                  className={`border px-3 py-1.5 text-xs uppercase tracking-wider transition ${
                    categories.includes(c) ? "border-accent text-accent" : "border-line text-muted hover:text-ink"
                  }`}
                >
                  {c}
                </button>
              ))}
            </div>
            <AddChip
              value={customCat}
              setValue={setCustomCat}
              placeholder="Add a category…"
              onAdd={(v) => {
                setCatOptions((o) => (o.includes(v) ? o : [...o, v]));
                setCategories((l) => (l.includes(v) ? l : [...l, v]));
              }}
            />
          </div>

          <div className="mb-3">
            <span className="mb-1 block text-muted uppercase tracking-wider text-xs">Targets</span>
            <div className="flex flex-wrap gap-2">
              {tgtOptions.map((t) => (
                <button
                  key={t}
                  onClick={() => setTargets((l) => toggle(l, t))}
                  className={`border px-3 py-1.5 text-xs uppercase tracking-wider transition ${
                    targets.includes(t) ? "border-accent text-accent" : "border-line text-muted hover:text-ink"
                  }`}
                >
                  {t}
                </button>
              ))}
            </div>
            <AddChip
              value={customTgt}
              setValue={setCustomTgt}
              placeholder="Add a target…"
              onAdd={(v) => {
                setTgtOptions((o) => (o.includes(v) ? o : [...o, v]));
                setTargets((l) => (l.includes(v) ? l : [...l, v]));
              }}
            />
          </div>

          <div className="mb-4 grid grid-cols-2 gap-4">
            <label className="text-sm">
              <span className="mb-1 block text-muted uppercase tracking-wider text-xs">Minimum score ({minScore})</span>
              <input
                type="range"
                min={0}
                max={100}
                value={minScore}
                onChange={(e) => setMinScore(Number(e.target.value))}
                className="w-full accent-[var(--accent)]"
              />
            </label>
            <label className="text-sm">
              <span className="mb-1 block text-muted uppercase tracking-wider text-xs">Max domains</span>
              <input
                type="number"
                min={1}
                max={500}
                value={maxDomains}
                onChange={(e) => setMaxDomains(Number(e.target.value))}
                className="w-full border border-line bg-base px-3 py-2 text-ink"
              />
            </label>
          </div>

          <label className="mb-4 flex items-center gap-2 text-sm text-muted">
            <input type="checkbox" checked={autoCrawl} onChange={(e) => setAutoCrawl(e.target.checked)} />
            Auto-crawl approved sources immediately
          </label>

          <button
            onClick={start}
            disabled={!!running || available === false}
            className="flex w-full items-center justify-center gap-2 border border-accent bg-accent/10 px-4 py-2.5 text-sm uppercase tracking-wider text-accent transition hover:bg-accent/20 disabled:opacity-40"
          >
            <Play size={16} /> {running ? "Discovery running…" : "Start discovery"}
          </button>
          {error && <p className="mt-2 text-sm text-red-400">{error}</p>}
        </section>

        {/* ── RUN PANEL ── */}
        <section className="border border-line bg-panel-2 p-5">
          <div className="mb-4 flex items-center justify-between">
            <span className="kai-metadata">DISCOVERY RUN</span>
            {run && (
              <span className={`text-xs uppercase tracking-wider ${running ? "text-accent" : "text-muted"}`}>
                {run.status}
              </span>
            )}
          </div>

          {!run ? (
            <p className="text-sm text-muted">No run yet. Configure and start discovery to see live progress.</p>
          ) : (
            <>
              <div className="mb-3 h-1.5 w-full bg-base">
                <div className="h-full bg-accent transition-all" style={{ width: `${run.progress}%` }} />
              </div>
              <div className="grid grid-cols-3 gap-3 text-center">
                <Stat label="Candidates" value={run.candidates} />
                <Stat label="Known" value={run.already_known} />
                <Stat label="New" value={run.new_domains} />
                <Stat label="Evaluated" value={run.evaluated} />
                <Stat label="Approved" value={run.approved} accent />
                <Stat label="Rejected" value={run.rejected} />
              </div>

              {run.current && (
                <div className="mt-4 border border-line bg-base p-3 text-sm">
                  <div className="kai-metadata mb-1">EVALUATING</div>
                  <div className="truncate font-mono text-ink">{run.current}</div>
                  {run.last && run.last.domain === run.current && (
                    <div className="mt-1 text-xs text-muted">SOURCE SCORE {run.last.score}/100</div>
                  )}
                </div>
              )}

              <div className="mt-4">
                <div className="kai-metadata mb-2">APPROVED SOURCES</div>
                <div className="max-h-72 space-y-1 overflow-auto">
                  {run.approved_list.length === 0 && <p className="text-sm text-muted">None yet.</p>}
                  {run.approved_list.map((ev) => (
                    <div key={ev.domain} className="flex items-center justify-between border border-line bg-base px-3 py-2 text-sm">
                      <span className="flex items-center gap-2 truncate">
                        <CheckCircle2 size={14} className="shrink-0 text-emerald-400" />
                        <span className="truncate font-mono">{ev.domain}</span>
                      </span>
                      <span className="shrink-0 text-xs text-muted">{ev.score}/100</span>
                    </div>
                  ))}
                </div>
              </div>
            </>
          )}
        </section>
      </div>

      {/* ── SELF-LEARNING TERMS ── */}
      <section className="border border-line bg-panel-2 p-5">
        <div className="mb-3 flex items-center justify-between">
          <span className="flex items-center gap-2 kai-metadata">
            <Sparkles size={14} className="text-accent" /> SELF-LEARNING QUEUE
          </span>
          {terms.length > 0 && (
            <button onClick={clearTerms} className="flex items-center gap-1 text-xs text-muted hover:text-red-400">
              <Trash2 size={13} /> Clear
            </button>
          )}
        </div>
        <p className="mb-3 text-sm text-muted">
          Searched terms with little or no local data. KAI discovers sources for the pending ones automatically.
        </p>
        {terms.length === 0 ? (
          <p className="text-sm text-muted">No learned terms yet.</p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {terms.map((t) => (
              <span
                key={t.term}
                title={`${t.kind} · searched ${t.count}× · ${t.local_hits ?? 0} local hits`}
                className={`flex items-center gap-1.5 border px-2.5 py-1 text-xs ${
                  t.pending ? "border-accent/60 text-accent" : "border-line text-muted"
                }`}
              >
                {t.pending ? <Sparkles size={11} /> : <XCircle size={11} className="opacity-50" />}
                <span className="font-mono">{t.term}</span>
                <span className="opacity-60">×{t.count}</span>
              </span>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function AddChip({
  value,
  setValue,
  placeholder,
  onAdd,
}: {
  value: string;
  setValue: (v: string) => void;
  placeholder: string;
  onAdd: (v: string) => void;
}) {
  function commit() {
    const v = normalize(value);
    if (v) onAdd(v);
    setValue("");
  }
  return (
    <div className="mt-2 flex gap-2">
      <input
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            commit();
          }
        }}
        placeholder={placeholder}
        className="flex-1 border border-line bg-base px-3 py-1.5 text-xs text-ink placeholder:text-muted/60"
      />
      <button
        type="button"
        onClick={commit}
        disabled={!value.trim()}
        className="border border-line px-3 py-1.5 text-xs uppercase tracking-wider text-muted transition hover:border-accent hover:text-accent disabled:opacity-40"
      >
        Add
      </button>
    </div>
  );
}

function Stat({ label, value, accent }: { label: string; value: number; accent?: boolean }) {
  return (
    <div className="border border-line bg-base px-2 py-3">
      <div className={`text-2xl font-semibold ${accent ? "text-accent" : "text-ink"}`}>{value}</div>
      <div className="kai-metadata mt-0.5">{label}</div>
    </div>
  );
}
