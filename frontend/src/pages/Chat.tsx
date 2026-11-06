import { useCallback, useEffect, useRef, useState } from "react";
import {
  Plus, Trash2, Send, Square, Wrench, AlertTriangle, Cpu, RefreshCw, Download, Play,
  FolderOpen, Globe, Search, ExternalLink, PanelLeftClose, PanelLeftOpen, Mic, ImagePlus, Camera,
} from "lucide-react";

import { useSearchParams } from "react-router-dom";
import {
  chatApi, streamMessage, attachStream, type Conversation, type ChatMessage, type ModelStatus,
  type Finding, type SseEvent, type ToolPreview,
} from "@/lib/chat";
import { useActiveRuns, pollActiveNow } from "@/lib/kaiWork";
import { PageLoading, Spinner } from "@/components/Async";
import { toolsApi } from "@/lib/tools";
import { Markdown } from "@/components/Markdown";
import { JsonView } from "@/components/JsonView";
import { ActionDeck, AGENT_LABELS } from "@/components/chat/ActionDeck";
import { MapCard } from "@/components/chat/MapCard";
import { humanSize, downloadKaiFile, toolGeoPoints, parseMapQuery } from "@/components/chat/util";
import { useVoice, speak, stopSpeaking } from "@/components/chat/useVoice";
import { FaceMatchCard } from "@/components/chat/FaceMatchCard";
import { facesApi } from "@/lib/faces";
import { peopleApi } from "@/lib/enrich";
import { PeopleResults } from "@/components/chat/PeopleResults";
import { ScanningStrip } from "@/components/ScanningStrip";
import { CameraCapture } from "@/components/chat/CameraCapture";

// Session preferences persist across reloads AND service restarts (localStorage).
const LS = {
  getBool(k: string, def: boolean): boolean {
    try { const v = localStorage.getItem(k); return v === null ? def : v === "1"; } catch { return def; }
  },
  setBool(k: string, v: boolean) { try { localStorage.setItem(k, v ? "1" : "0"); } catch { /* */ } },
  getStr(k: string, def: string): string {
    try { return localStorage.getItem(k) ?? def; } catch { return def; }
  },
  setStr(k: string, v: string) { try { localStorage.setItem(k, v); } catch { /* */ } },
};

interface ToolEvent {
  operation: string;
  params?: any;
  result?: any;
  skipped?: boolean;
}
interface PendingApproval {
  operation: string;
  params: Record<string, any>;
  preview: ToolPreview;
  step: number;
}
interface LiveTurn {
  content: string;
  tools: ToolEvent[];
  findings: Finding[];
  error: string | null;
  thinking: boolean;
  pending: PendingApproval | null;
  agentInfo: { agent: string; reason: string }[] | null;
}

const SEV_COLOR: Record<string, string> = {
  critical: "var(--kai-accent)", high: "var(--kai-accent)", medium: "#f59e0b",
  low: "var(--kai-hud)", info: "var(--kai-hud)",
};

function applyEvent(turn: LiveTurn, e: SseEvent) {
  if (e.event === "thinking") turn.thinking = true;
  else if (e.event === "agent_selected") { (turn.agentInfo ||= []).push({ agent: e.data.agent, reason: e.data.reason }); }
  else if (e.event === "tool_proposed") {
    turn.pending = { operation: e.data.operation, params: e.data.params, preview: e.data.preview, step: e.data.step };
    turn.thinking = false;
  } else if (e.event === "tool_call") {
    turn.pending = null;   // approved (or auto-approved) — now actually running
    turn.tools.push({ operation: e.data.operation, params: e.data.params });
    turn.thinking = false;
  } else if (e.event === "tool_denied") {
    turn.pending = null;
    turn.tools.push({ operation: e.data.operation, params: e.data.params, skipped: true });
    turn.thinking = false;
  } else if (e.event === "tool_result") {
    const last = turn.tools[turn.tools.length - 1];
    if (last && last.operation === e.data.operation) last.result = e.data.result;
    else turn.tools.push({ operation: e.data.operation, result: e.data.result });
  } else if (e.event === "token") { turn.content += e.data.text; turn.thinking = false; }
  else if (e.event === "message" || e.event === "final") {
    turn.content = e.data.answer ?? e.data.content ?? turn.content;
    if (e.data.findings) turn.findings = e.data.findings;
    turn.thinking = false;
  } else if (e.event === "error") { turn.error = e.data.message || e.data.code; turn.thinking = false; }
}

function ModelBadge({ status }: { status: ModelStatus | null }) {
  if (!status) return <span className="kai-metadata">checking model…</span>;
  const ok = status.ready;
  const color = ok ? "var(--kai-verified)" : "var(--kai-accent)";
  return (
    <div className="flex items-center gap-2" title={status.error || status.endpoint}>
      <Cpu size={14} style={{ color }} />
      <span className="hud-mono text-xs" style={{ color }}>
        {status.model} · {ok ? "ready" : status.reachable ? (status.backend === "llamacpp" ? "loading / unavailable" : "model missing") : "offline"}
        {ok && status.backend ? ` · ${status.backend === "llamacpp" ? "llama.cpp" : "Ollama"}` : ""}
        {ok && status.accelerator ? ` · ${status.accelerator}` : ""}
      </span>
    </div>
  );
}

function InstallNow({ tool, onDone }: { tool: string; onDone?: () => void }) {
  const [state, setState] = useState<"idle" | "busy" | "done" | "error">("idle");
  const [note, setNote] = useState("");
  async function go() {
    setState("busy"); setNote("Waiting for the system password prompt…");
    try {
      const r = await toolsApi.installNow({ capability: tool });
      if (r.verify?.installed) {
        setState("done");
        setNote(`${tool} installed${r.verify.version ? ` (${r.verify.version})` : ""} — ask again to run it.`);
        onDone?.();
      } else {
        setState("error");
        setNote(r.outcome?.sudo_needs_password
          ? "sudo needs a password — set TOOL_INSTALL_HELPER=pkexec or add a NOPASSWD rule."
          : (r.request?.log?.split("\n").filter((l: string) => l.startsWith("E:")).join(" ") || r.request?.log?.slice(-300))
            || r.outcome?.error || "install failed");
      }
    } catch (e: any) { setState("error"); setNote(e?.message || "install failed"); }
  }
  return (
    <div className="mt-2 flex flex-wrap items-center gap-2">
      {state !== "done" && (
        <button onClick={go} disabled={state === "busy"}
          className="flex items-center gap-1 rounded border border-line px-2 py-1 hover:bg-panel disabled:opacity-40"
          style={{ color: "var(--kai-verified)" }}>
          {state === "busy" ? <Spinner size={12} /> : <Download size={12} />}
          {state === "error" ? "retry install" : `Install ${tool} now`}
        </button>
      )}
      {note && <span className="kai-metadata" style={{ color: state === "error" ? "var(--kai-accent)" : undefined }}>{note}</span>}
    </div>
  );
}

function ApprovalCard({ pending, onDecide, busy }: {
  pending: PendingApproval; onDecide: (approved: boolean) => void; busy: boolean;
}) {
  const p = pending.preview;
  const blocked = !p || !p.ok;
  return (
    <div className="my-2 rounded border p-3 text-xs" style={{ borderColor: "#f59e0b" }}>
      <div className="flex items-center gap-2">
        <Wrench size={13} style={{ color: "#f59e0b" }} />
        <span className="hud-mono font-semibold" style={{ color: "#f59e0b" }}>KAI wants to run</span>
        <span className="hud-mono" style={{ color: "var(--kai-hud)" }}>{pending.operation}</span>
        {p?.posture && <span className="kai-metadata uppercase">{p.posture}</span>}
      </div>
      {!blocked && (
        <pre className="mt-2 overflow-auto whitespace-pre-wrap break-words rounded border border-line bg-panel px-2 py-1.5 font-mono text-[12px]" style={{ color: "var(--kai-hud)" }}>
          $ {p.preview}
        </pre>
      )}
      {blocked && (
        <div className="mt-2 text-muted">{p?.message || p?.error || "This tool call cannot run."}</div>
      )}
      {p?.needs_authorization && (
        <div className="mt-1" style={{ color: "#f59e0b" }}>
          Approving this will also add “{p.target}” to your authorized-targets list (active scan).
        </div>
      )}
      {pending.params && Object.keys(pending.params).length > 0 && (
        <div className="kai-metadata mt-1">{Object.entries(pending.params).map(([k, v]) => `${k}=${v}`).join("  ")}</div>
      )}
      <div className="mt-2 flex items-center gap-2">
        <button onClick={() => onDecide(true)} disabled={busy || blocked}
          className="flex items-center gap-1 rounded border px-3 py-1.5 font-semibold disabled:opacity-40"
          style={{ borderColor: "var(--kai-verified)", color: "var(--kai-verified)" }}>
          <Play size={12} /> Go ahead
        </button>
        <button onClick={() => onDecide(false)} disabled={busy}
          className="rounded border border-line px-3 py-1.5 hover:bg-panel disabled:opacity-40">
          Skip
        </button>
      </div>
    </div>
  );
}

// A real-terminal view of a command KAI ran: the command line + its output.
function TerminalBlock({ cmd, out, exit, root }: {
  cmd: string; out?: string; exit?: number | null; root?: boolean;
}) {
  return (
    <div className="mt-2 overflow-hidden rounded-md border" style={{ borderColor: "#262b36", background: "#0b0e14" }}>
      <div className="flex items-center gap-1.5 border-b px-2 py-1" style={{ borderColor: "#1a1e27", background: "#11151d" }}>
        <span className="h-2 w-2 rounded-full" style={{ background: "#ff5f56" }} />
        <span className="h-2 w-2 rounded-full" style={{ background: "#ffbd2e" }} />
        <span className="h-2 w-2 rounded-full" style={{ background: "#27c93f" }} />
        <span className="ml-1 font-mono text-[10px]" style={{ color: "#6b7280" }}>
          terminal{root ? " · root" : ""}
        </span>
      </div>
      <pre className="max-h-80 overflow-auto px-3 py-2 font-mono text-[11px] leading-relaxed" style={{ color: "#cbd5e1" }}>
        <div>
          <span style={{ color: root ? "#f87171" : "#4ade80" }}>{root ? "#" : "$"}</span>{" "}
          <span style={{ color: "#e5e7eb" }}>{cmd}</span>
        </div>
        {out && out.trim() && <div className="whitespace-pre-wrap break-words" style={{ color: "#9ca3af" }}>{out.trimEnd()}</div>}
        {typeof exit === "number" && exit !== 0 && (
          <div style={{ color: "#f87171" }}>[exit {exit}]</div>
        )}
      </pre>
    </div>
  );
}

function WebResultBlock({ op, r }: { op: string; r: any }) {
  const [openPage, setOpenPage] = useState(false);
  if (op === "web.search") {
    const results: any[] = Array.isArray(r.results) ? r.results : [];
    return (
      <div className="mt-2 overflow-hidden rounded-md border" style={{ borderColor: "#262b36", background: "#0b0e14" }}>
        <div className="flex items-center gap-1.5 border-b px-2 py-1" style={{ borderColor: "#1a1e27", background: "#11151d" }}>
          <Search size={11} style={{ color: "var(--kai-hud)" }} />
          <span className="font-mono text-[10px]" style={{ color: "#6b7280" }}>
            {r.query ? `search · ${r.query}` : "web search"}{typeof r.count === "number" ? ` · ${r.count}` : ""}
          </span>
        </div>
        <div className="max-h-96 overflow-auto p-1">
          {results.length === 0 && <div className="px-2 py-1 text-[11px] text-muted">No results.</div>}
          {results.map((x, i) => (
            <a key={i} href={x.url} target="_blank" rel="noopener noreferrer"
               className="block rounded px-2 py-1.5 hover:bg-panel-2">
              <div className="flex items-center gap-1 text-[12px]" style={{ color: "var(--kai-hud)" }}>
                <ExternalLink size={11} className="shrink-0" />
                <span className="truncate font-medium">{x.title}</span>
              </div>
              <div className="truncate text-[10px]" style={{ color: "#4ade80" }}>{x.url}</div>
              {x.snippet && <div className="mt-0.5 text-[11px] leading-snug text-muted">{x.snippet}</div>}
            </a>
          ))}
        </div>
      </div>
    );
  }
  // web.open
  const text: string = r.text || "";
  return (
    <div className="mt-2 overflow-hidden rounded-md border" style={{ borderColor: "#262b36", background: "#0b0e14" }}>
      <div className="flex items-center gap-1.5 border-b px-2 py-1" style={{ borderColor: "#1a1e27", background: "#11151d" }}>
        <Globe size={11} style={{ color: "var(--kai-hud)" }} />
        <a href={r.url} target="_blank" rel="noopener noreferrer"
           className="truncate font-mono text-[10px] hover:underline" style={{ color: "#6b7280" }}>
          {r.title || r.url || "page"}
        </a>
        {text && (
          <button onClick={() => setOpenPage(v => !v)} className="ml-auto text-[10px] text-muted hover:text-white">
            {openPage ? "hide" : `read ${text.length} chars`}
          </button>
        )}
      </div>
      {openPage && text && (
        <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words px-3 py-2 text-[11px] leading-relaxed" style={{ color: "#9ca3af" }}>
          {text}{r.truncated ? "\n…[truncated]" : ""}
        </pre>
      )}
    </div>
  );
}

function ToolCard({ t }: { t: ToolEvent }) {
  if (t.skipped) {
    return (
      <div className="my-2 rounded border border-line bg-panel-2 p-2 text-xs">
        <div className="flex items-center gap-2">
          <Wrench size={12} className="text-muted" />
          <span className="hud-mono text-muted">{t.operation}</span>
          <span className="hud-mono" style={{ color: "#f59e0b" }}>● declined</span>
        </div>
        <div className="kai-metadata mt-1">You chose Skip — KAI did not run this.</div>
      </div>
    );
  }
  const r = t.result || {};
  const notInstalled = r.reason === "tool_not_installed" && r.tool && (r.install_hint?.source ?? "apt") === "apt";
  const status = r.status || (r.ok ? "ok" : "…");
  const color = r.ok ? "var(--kai-verified)" : status === "denied" || status === "blocked" ? "#f59e0b" : "var(--kai-accent)";
  const out = (r.stdout || "") + (r.stderr ? "\n" + r.stderr : "");
  // The terminal command for this run: the shell command the model typed, or
  // the real command line the backend executed for a catalogue tool.
  const isShell = t.operation === "shell.run" || r.posture === "shell" || r.posture === "shell-root";
  const isWeb = t.operation === "web.search" || t.operation === "web.open" || r.posture === "web";
  const isIdentity = (t.operation === "identity.lookup" || r.operation === "identity.lookup")
    && Array.isArray(r.result?.people);
  const invCase = r.posture === "investigation" && r.result && r.result.id && r.result.code ? r.result : null;
  const root = r.posture === "shell-root" || t.params?.sudo === true;
  const cmd = (isShell ? (t.params?.command as string) : undefined) || r.argv_display || "";
  const showTerminal = !isWeb && !!(cmd || out.trim());
  return (
    <div className="my-2 rounded border border-line bg-panel-2 p-2 text-xs">
      <div className="flex items-center gap-2">
        <Wrench size={12} style={{ color: "var(--kai-hud)" }} />
        <span className="hud-mono" style={{ color: "var(--kai-hud)" }}>{t.operation}</span>
        <span className="hud-mono" style={{ color }}>● {status}</span>
        {r.posture && <span className="kai-metadata uppercase">{r.posture}</span>}
      </div>
      {/* Non-command params (e.g. target=…), shown for catalogue tools only. */}
      {!isShell && t.params && Object.keys(t.params).length > 0 && (
        <div className="kai-metadata mt-1">{Object.entries(t.params).map(([k, v]) => `${k}=${v}`).join("  ")}</div>
      )}
      {(r.message || r.error) && <div className="mt-1" style={{ color }}>{r.message || r.error}</div>}
      {notInstalled && <InstallNow tool={r.tool} />}
      {r.reason === "tool_not_installed" && !notInstalled && r.install_hint && (
        <div className="kai-metadata mt-1">Source “{r.install_hint.source}” — install it manually, then retry.</div>
      )}
      {showTerminal && <TerminalBlock cmd={cmd} out={out} exit={r.exit_code} root={root} />}
      {isWeb && r.ok && <WebResultBlock op={t.operation} r={r} />}
      {(() => {
        const geo = toolGeoPoints(r);
        const isMap = t.operation === "maps.find" || r.operation === "maps.find";
        if (isMap) {
          const q = String(t.params?.query ?? r.query ?? "");
          const mq = parseMapQuery(q);
          if (geo.length > 0) return <MapCard points={geo} query={q} autoAmenity={mq.amenity} />;
          if (mq.nearMe || mq.amenity) return <MapCard points={[]} query={q} autoLocate autoAmenity={mq.amenity} />;
          return null;
        }
        return geo.length > 0 ? <MapCard points={geo} /> : null;
      })()}
      {invCase && (
        <a href={`/investigations/${invCase.id}`} target="_blank" rel="noopener noreferrer"
           className="mt-2 flex items-center gap-2 rounded border border-line bg-panel px-2 py-1.5 hover:bg-panel-2">
          <FolderOpen size={13} style={{ color: "var(--kai-hud)" }} />
          <span className="hud-mono text-[11px]" style={{ color: "var(--kai-hud)" }}>{invCase.code}</span>
          <span className="truncate text-[11px]">{invCase.name}</span>
          <ExternalLink size={11} className="ml-auto text-muted" />
        </a>
      )}
      {r.file && <FileChip f={r.file} />}
      {Array.isArray(r.files) && r.files.length > 0 && (
        <div className="mt-1 grid gap-1">
          {r.files.map((f: any) => <FileChip key={f.id} f={f} />)}
        </div>
      )}
      {isIdentity && <PeopleResults r={{ people: r.result.people, notes: r.result.note ? [r.result.note] : [] }} />}
      {r.result && !isIdentity && <JsonView value={r.result} />}
    </div>
  );
}

function FileChip({ f }: { f: { id: string; name: string; size?: number; download_url: string } }) {
  return (
    <button
      onClick={() => downloadKaiFile(f)}
      className="mt-1 flex w-full items-center gap-2 rounded border border-line bg-panel px-2 py-1.5 text-left hover:bg-panel-2"
      title={`Download ${f.name}`}
    >
      <Download size={13} style={{ color: "var(--kai-hud)" }} />
      <span className="hud-mono truncate text-[11px]">{f.name}</span>
      <span className="kai-metadata ml-auto whitespace-nowrap">{humanSize(f.size)}</span>
    </button>
  );
}

function FindingCard({ f }: { f: Finding }) {
  const color = SEV_COLOR[f.severity?.toLowerCase()] || "var(--kai-hud)";
  return (
    <div className="my-2 rounded border-l-2 bg-panel-2 p-3 text-xs" style={{ borderColor: color }}>
      <div className="flex items-center gap-2">
        <AlertTriangle size={12} style={{ color }} />
        <span className="font-semibold" style={{ color }}>{f.title}</span>
        <span className="hud-mono uppercase" style={{ color }}>{f.severity}</span>
        <span className="kai-metadata">· {f.status === f.confidence ? f.status : `${f.confidence} · ${f.status}`}</span>
      </div>
      {f.asset && <div className="kai-metadata mt-1">asset: {f.asset}{f.tool ? ` · tool: ${f.tool}` : ""}</div>}
      {f.description && <div className="mt-1 text-ink">{f.description}</div>}
      {f.evidence && f.evidence.length > 0 && (
        <div className="mt-1"><span className="kai-metadata">evidence:</span>
          <ul className="ml-4 list-disc text-muted">{f.evidence.map((e, i) => <li key={i}>{e}</li>)}</ul>
        </div>
      )}
      {f.impact && <div className="mt-1"><span className="kai-metadata">impact:</span> {f.impact}</div>}
      {f.remediation && <div className="mt-1"><span className="kai-metadata">remediation:</span> {f.remediation}</div>}
      {f.validation && <div className="mt-1"><span className="kai-metadata">validation:</span> {f.validation}</div>}
      {f.limitations && <div className="mt-1"><span className="kai-metadata">limitations:</span> {f.limitations}</div>}
    </div>
  );
}

function MessageBubble({ m, onPick }: { m: ChatMessage; onPick?: (t: string) => void }) {
  const isUser = m.role === "user";
  const findings: Finding[] = m.meta?.findings || [];
  const faceSearch = m.meta?.faceSearch;
  const peopleSearch = m.meta?.peopleSearch;
  return (
    <div className={`mb-4 ${isUser ? "text-right" : ""}`}>
      <div className="kai-metadata mb-1">{isUser ? "OPERATOR" : "KAI"}</div>
      <div className={`inline-block max-w-full rounded px-3 py-2 text-sm ${isUser ? "bg-panel-2" : "bg-panel"}`}>
        {isUser
          ? <div className="whitespace-pre-wrap break-words text-left">{m.content}</div>
          : <Markdown>{m.content}</Markdown>}
      </div>
      {!isUser && faceSearch && <FaceMatchCard r={faceSearch} onAsk={onPick} />}
      {!isUser && peopleSearch && <PeopleResults r={peopleSearch} />}
      {!isUser && (m.tool_calls || []).map((t: any, i: number) => <ToolCard key={i} t={t} />)}
      {!isUser && findings.map((f, i) => <FindingCard key={i} f={f} />)}
    </div>
  );
}

export function Chat() {
  const [status, setStatus] = useState<ModelStatus | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  // Agentic defaults ON (KAI acts on its own); all persist across restarts.
  const [useTools, setUseTools] = useState(() => LS.getBool("kai.useTools", true));
  const [autoApprove, setAutoApprove] = useState(() => LS.getBool("kai.autoApprove", true));
  // Qwen3-style reasoning: slower on CPU. Remembered per conversation (kai.think.<id>).
  const [think, setThink] = useState(false);
  // Agent: "auto" lets the backend route each turn; otherwise force a specialist.
  const [agent, setAgent] = useState(() => LS.getStr("kai.agent", "auto"));
  // Voice: hands-free. wake = require "KAI …" before acting; speak = read replies aloud.
  const [wakeOn, setWakeOn] = useState(() => LS.getBool("kai.wake", false));
  const [speakOn, setSpeakOn] = useState(() => LS.getBool("kai.speak", false));
  // Where KAI searches an uploaded face. Both can be on → search index AND web
  // together for fuller coverage. Both default ON.
  const [scopeDb, setScopeDb] = useState(() => LS.getBool("kai.scopeDb", true));
  const [scopeWeb, setScopeWeb] = useState(() => LS.getBool("kai.scopeWeb", true));
  useEffect(() => { LS.setBool("kai.useTools", useTools); }, [useTools]);
  useEffect(() => { LS.setBool("kai.autoApprove", autoApprove); }, [autoApprove]);
  useEffect(() => { LS.setStr("kai.agent", agent); }, [agent]);
  useEffect(() => { LS.setBool("kai.wake", wakeOn); }, [wakeOn]);
  useEffect(() => { LS.setBool("kai.speak", speakOn); }, [speakOn]);
  useEffect(() => { LS.setBool("kai.scopeDb", scopeDb); }, [scopeDb]);
  useEffect(() => { LS.setBool("kai.scopeWeb", scopeWeb); }, [scopeWeb]);
  const speakRef = useRef(false);
  useEffect(() => { speakRef.current = speakOn; if (!speakOn) stopSpeaking(); }, [speakOn]);
  const [stopping, setStopping] = useState<Set<string>>(new Set());
  const [faceBusy, setFaceBusy] = useState(false);
  const [scanCrops, setScanCrops] = useState<string[]>([]);
  const [showCamera, setShowCamera] = useState(false);
  const [facePreview, setFacePreview] = useState<string | null>(null);
  const facePreviewRef = useRef<string | null>(null);
  const imgInputRef = useRef<HTMLInputElement | null>(null);
  function setPreview(url: string | null) {
    if (facePreviewRef.current) URL.revokeObjectURL(facePreviewRef.current);
    facePreviewRef.current = url;
    setFacePreview(url);
  }
  useEffect(() => () => { if (facePreviewRef.current) URL.revokeObjectURL(facePreviewRef.current); }, []);
  const [selectedModel, setSelectedModel] = useState<string>("");
  const [deciding, setDeciding] = useState(false);
  const [live, setLive] = useState<LiveTurn | null>(null);
  const [streaming, setStreaming] = useState(false);
  const [convLoading, setConvLoading] = useState(false);
  // Left conversation rail can collapse to give the transcript + Action Deck room.
  const [leftOpen, setLeftOpen] = useState(true);
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const lastSentRef = useRef<string>("");
  const activeIdRef = useRef<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const [params, setParams] = useSearchParams();
  const runs = useActiveRuns(2000);
  const workingIds = new Set(runs.map((r) => r.conversation_id));
  useEffect(() => { activeIdRef.current = activeId; }, [activeId]);

  // Hands-free voice. A heard utterance is sent as an ordinary turn — it never
  // bypasses the tool approval gate; auto-run/root behave exactly as configured.
  const voice = useVoice({
    onFinal: (text) => { send(text); },
    onInterim: (text) => { setInput(text); },
  });
  function toggleMic() {
    if (!voice.supported) return;
    if (voice.listening) voice.stop(); else voice.start({ wake: wakeOn });
  }
  function changeWake(v: boolean) { setWakeOn(v); if (voice.listening) voice.start({ wake: v }); }

  const loadConversations = useCallback(async () => {
    try { setConversations(await chatApi.listConversations()); } catch { /* */ }
  }, []);

  useEffect(() => {
    chatApi.status().then((s) => {
      setStatus(s);
      setSelectedModel((cur) => cur || s.model);
    }).catch(() => setStatus(null));
    loadConversations();
    const id = setInterval(() => chatApi.status().then(setStatus).catch(() => {}), 15000);
    return () => clearInterval(id);
  }, [loadConversations]);

  // Switch the model for the current conversation (or the next one to be created).
  const changeModel = useCallback(async (model: string) => {
    setSelectedModel(model);
    const id = activeIdRef.current;
    if (id) {
      try {
        await chatApi.setConversationModel(id, model);
        loadConversations();
      } catch { /* kept locally; applied when the next turn starts */ }
    }
  }, [loadConversations]);

  // Follow a turn that is running on the server (also used after navigating back).
  const followRun = useCallback(async (id: string) => {
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    const turn: LiveTurn = { content: "", tools: [], findings: [], error: null, thinking: true, pending: null, agentInfo: null };
    setLive({ ...turn });
    setStreaming(true);
    try {
      await attachStream(id, (e) => {
        applyEvent(turn, e);
        setLive({ ...turn, tools: [...turn.tools], findings: [...turn.findings] });
      }, ctrl.signal);
    } catch { /* aborted / network drop: the run continues server-side */ }
    if (abortRef.current === ctrl) {
      abortRef.current = null;
      setStreaming(false);
      setLive(null);
      if (speakRef.current && turn.content) speak(turn.content);
      if (activeIdRef.current === id && !ctrl.signal.aborted) {
        try { setMessages((await chatApi.getConversation(id)).messages); } catch { /* */ }
      }
      loadConversations();
      pollActiveNow();
    }
  }, [loadConversations]);

  const openConversation = useCallback(async (id: string) => {
    abortRef.current?.abort();
    abortRef.current = null;
    setStreaming(false);
    setActiveId(id);
    setLive(null);
    setConvLoading(true);
    try {
      const detail = await chatApi.getConversation(id);
      setMessages(detail.messages);
      if (detail.model) setSelectedModel(detail.model);
      try { setThink(localStorage.getItem(`kai.think.${id}`) === "1"); } catch { /* storage blocked */ }
    } catch { setMessages([]); }
    finally { setConvLoading(false); }
    // If KAI is still working on this conversation, pick the live turn back up.
    try {
      const active = await chatApi.active();
      if (active.some((r) => r.conversation_id === id)) followRun(id);
    } catch { /* */ }
  }, [followRun]);

  // Deep-link from the global "KAI is working" pill: /chat?c=<conversation id>
  useEffect(() => {
    const c = params.get("c");
    if (c && c !== activeIdRef.current) openConversation(c);
    if (c) setParams({}, { replace: true });
  }, [params, setParams, openConversation]);

  // Leaving the page only detaches this view; the turn keeps running on the server.
  useEffect(() => () => { abortRef.current?.abort(); }, []);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, live]);

  function pushMsg(role: "user" | "assistant", content: string, meta: any = {}) {
    setMessages((m) => [...m, {
      id: `local-${role}-${Date.now()}`, role, content,
      tool_calls: null, tool_results: null, meta, created_at: new Date().toISOString(),
    }]);
  }

  // Attach an image → face search. Runs the KAI index and/or the web, per the
  // operator's scope choice; both selected → search both for fuller coverage.
  async function onImage(file: File) {
    if (!file || faceBusy) return;
    if (!scopeDb && !scopeWeb) {
      pushMsg("assistant", "Select **DB** and/or **Web** (next to the attach button) before uploading an image.");
      return;
    }
    if (!activeId) {
      const c = await chatApi.createConversation({ model: selectedModel || undefined });
      setActiveId(c.id);
      loadConversations();
    }
    const where = [scopeDb && "KAI index", scopeWeb && "web"].filter(Boolean).join(" + ");
    pushMsg("user", `🖼 ${file.name} — face search (${where})`);
    setPreview(URL.createObjectURL(file));
    setFaceBusy(true);
    // Fuel the scanning animation with recent indexed crops (fetched once).
    if (scanCrops.length === 0) {
      facesApi.indexSample(48).then((d) => setScanCrops(d.samples.map((s) => s.crop_url))).catch(() => { /* */ });
    }
    if (scopeDb) {
      try {
        // One combined search: face index (NID photos + web faces), ≥49% only,
        // each person with their record and the parents/siblings found in the system.
        const r = await peopleApi.search({ file });
        const n = r.faces_detected ?? 0;
        const pc = r.face_matches?.length ?? (r.people.length + (r.web_matches?.length ?? 0));
        const summary = n === 0
          ? "**KAI index:** no face detected in that image."
          : `**KAI index:** ${n} face${n === 1 ? "" : "s"} detected; ${pc} face match${pc === 1 ? "" : "es"} at 49% or higher across the whole index (ID photos + web)${r.people.length ? `, linked to ${r.people.length} ID record${r.people.length === 1 ? "" : "s"}` : ""}. Potential matches only — not confirmed identities.`;
        pushMsg("assistant", summary, { peopleSearch: r });
      } catch (e: any) {
        pushMsg("assistant", `⚠ KAI-index face search failed: ${e?.message || "error"}`);
      }
    }
    if (scopeWeb) {
      try {
        const r = await facesApi.discover(file);
        if (!r.available) {
          pushMsg("assistant", `**Web:** reverse-image search unavailable — no provider configured. ${r.hint || "Add a provider key (e.g. SERPAPI_API_KEY) and enable it in Power Up."}`);
        } else {
          const ms = r.matches || [];
          const content = ms.length === 0
            ? `**Web:** reverse-image search ran (${r.candidates_seen ?? 0} candidates) but found no verified matches.`
            : `**Web reverse-image matches** — ${r.candidates_seen ?? 0} candidates, ${ms.length} verified:\n\n`
              + ms.slice(0, 8).map((m) => `- [${m.title || m.source_url || "source"}](${m.source_url || m.image_url || "#"}) — ${Math.round((m.similarity || 0) * 100)}%`).join("\n");
          pushMsg("assistant", content);
        }
      } catch (e: any) {
        pushMsg("assistant", `⚠ Web face search failed: ${e?.message || "error"}`);
      }
    }
    setFaceBusy(false);
  }

  // Capability palette → scaffold an editable prompt into the composer and focus it.
  function pickCapability(text: string) {
    setInput(text);
    requestAnimationFrame(() => {
      const el = textareaRef.current;
      if (!el) return;
      el.focus();
      const blank = text.indexOf("<");
      if (blank >= 0) el.setSelectionRange(blank, text.indexOf(">", blank) + 1 || blank);
    });
  }
  async function stopRun(convId: string) {
    setStopping((s) => new Set(s).add(convId));
    try { await chatApi.cancel(convId); } catch { /* */ }
    pollActiveNow();
    setTimeout(() => setStopping((s) => { const n = new Set(s); n.delete(convId); return n; }), 1500);
  }

  async function newConversation() {
    const c = await chatApi.createConversation({ model: selectedModel || undefined });
    await loadConversations();
    setActiveId(c.id);
    setMessages([]);
    setLive(null);
  }

  async function removeConversation(id: string) {
    await chatApi.deleteConversation(id);
    if (activeId === id) { setActiveId(null); setMessages([]); }
    loadConversations();
  }

  async function send(forced?: string) {
    const content = (forced ?? input).trim();
    if (!content || streaming) return;
    stopSpeaking();
    lastSentRef.current = content;
    let convId = activeId;
    if (!convId) {
      const c = await chatApi.createConversation({ model: selectedModel || undefined });
      convId = c.id;
      setActiveId(c.id);
      loadConversations();
    }
    if (forced === undefined) setInput("");
    setMessages((m) => [...m, {
      id: `local-${Date.now()}`, role: "user", content, tool_calls: null,
      tool_results: null, meta: {}, created_at: new Date().toISOString(),
    }]);
    const turn: LiveTurn = { content: "", tools: [], findings: [], error: null, thinking: true, pending: null, agentInfo: null };
    setLive({ ...turn });
    setStreaming(true);
    const ctrl = new AbortController();
    abortRef.current = ctrl;

    try {
      await streamMessage(convId!, content, useTools, (e) => {
        applyEvent(turn, e);
        setLive({ ...turn, tools: [...turn.tools], findings: [...turn.findings] });
      }, ctrl.signal, autoApprove, think, agent === "auto" ? undefined : agent);
    } catch (err: any) {
      if (ctrl.signal.aborted) return;   // navigated away: the turn continues server-side
      // connection dropped mid-turn: if KAI is still on it, re-attach instead of failing
      try {
        if ((await chatApi.active()).some((r) => r.conversation_id === convId)) { followRun(convId!); return; }
      } catch { /* */ }
      turn.error = err?.message || "stream failed";
    } finally {
      if (ctrl.signal.aborted || abortRef.current !== ctrl) return;
      setStreaming(false);
      abortRef.current = null;
      // Commit the live turn into the message list as a persisted-style assistant message.
      setMessages((m) => [...m, {
        id: `local-a-${Date.now()}`, role: "assistant",
        content: turn.content || (turn.error ? `⚠ ${turn.error}` : ""),
        tool_calls: turn.tools as any, tool_results: null,
        meta: { findings: turn.findings, error: turn.error }, created_at: new Date().toISOString(),
      }]);
      setLive(null);
      if (speakRef.current && turn.content) speak(turn.content);
      loadConversations();
    }
  }

  function cancel() {
    // Really stop the server-side turn (leaving the page does NOT).
    if (activeId) chatApi.cancel(activeId).catch(() => {});
  }

  async function decide(approved: boolean) {
    if (!activeId || deciding) return;
    setDeciding(true);
    try { await chatApi.approve(activeId, approved); } catch { /* the SSE stream reports the real outcome */ }
    setDeciding(false);
  }

  function retryLast() {
    const last = messages[messages.length - 1];
    // Drop the failed assistant turn so the retry replaces it.
    if (last && last.role === "assistant" && (last.meta?.error || last.meta?.cancelled)) {
      setMessages((m) => m.slice(0, -1));
    }
    const content = lastSentRef.current
      || [...messages].reverse().find((m) => m.role === "user")?.content
      || "";
    if (content) send(content);
  }

  const lastMsg = messages[messages.length - 1];
  const showRetry = !streaming && !live && lastMsg?.role === "assistant"
    && (lastMsg.meta?.error || lastMsg.meta?.cancelled);

  return (
    <div className="flex h-[calc(100vh-7rem)] gap-3">
      {/* conversation history — collapsible */}
      {leftOpen ? (
        <aside className="hidden w-60 shrink-0 flex-col md:flex">
          <div className="mb-2 flex items-center gap-1.5">
            <button onClick={newConversation}
              className="flex flex-1 items-center justify-center gap-2 rounded border border-line px-3 py-2 text-sm hover:bg-panel">
              <Plus size={14} /> New conversation
            </button>
            <button onClick={() => setLeftOpen(false)} title="Collapse"
              className="rounded border border-line p-2 text-muted hover:bg-panel hover:text-ink">
              <PanelLeftClose size={15} />
            </button>
          </div>
          <div className="flex-1 space-y-1 overflow-auto">
            {conversations.map((c) => (
              <div key={c.id}
                className={`group flex items-center justify-between rounded px-2 py-2 text-sm cursor-pointer ${activeId === c.id ? "bg-panel" : "hover:bg-panel-2"}`}
                onClick={() => openConversation(c.id)}>
                <span className="flex min-w-0 items-center gap-2">
                  {workingIds.has(c.id) && (
                    <span title="KAI is working on this" className="h-1.5 w-1.5 shrink-0 animate-pulse rounded-full"
                      style={{ background: "var(--kai-hud)" }} />
                  )}
                  <span className="truncate">{c.title}</span>
                </span>
                <button onClick={(e) => { e.stopPropagation(); removeConversation(c.id); }}
                  className="opacity-0 group-hover:opacity-100" title="Delete">
                  <Trash2 size={13} className="text-muted hover:text-ink" />
                </button>
              </div>
            ))}
            {conversations.length === 0 && <div className="kai-metadata px-2">No conversations yet.</div>}
          </div>
        </aside>
      ) : (
        <aside className="hidden w-10 shrink-0 flex-col items-center gap-2 md:flex">
          <button onClick={() => setLeftOpen(true)} title="Show conversations"
            className="rounded border border-line p-2 text-muted hover:bg-panel hover:text-ink" style={{ color: "var(--kai-hud)" }}>
            <PanelLeftOpen size={15} />
          </button>
          <button onClick={newConversation} title="New conversation"
            className="rounded border border-line p-2 text-muted hover:bg-panel hover:text-ink">
            <Plus size={15} />
          </button>
        </aside>
      )}

      {/* main chat */}
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="mb-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="hud-mono text-xs" style={{ color: "var(--kai-hud)" }}>◢◤</span>
            <h1 className="hud-mono hud-glow text-lg font-semibold tracking-wide" style={{ color: "var(--kai-hud)" }}>KAI CONSOLE</h1>
            <span className="h-1.5 w-1.5 animate-pulse rounded-full" style={{ background: status?.ready ? "var(--kai-verified)" : "var(--kai-accent)" }} />
          </div>
          <ModelBadge status={status} />
        </div>

        {status && !status.ready && (
          <div className="mb-3 rounded border border-line bg-panel-2 p-3 text-xs" style={{ borderColor: "var(--kai-accent)" }}>
            <div className="flex items-center gap-2" style={{ color: "var(--kai-accent)" }}>
              <AlertTriangle size={14} /> Model not ready
            </div>
            <div className="mt-1 text-muted">
              {status.backend === "llamacpp"
                ? (status.error || `llama.cpp at ${status.endpoint} is not ready.`) + "  Start it with:  systemctl --user start kai-llama"
                : status.reachable
                ? `Ollama is reachable at ${status.endpoint} but the model "${status.model}" is not installed. Install it with:  ollama pull ${status.model}  (or create it from your Modelfile).`
                : `Cannot reach Ollama at ${status.endpoint}. Start it with:  ollama serve  — ${status.error ?? ""}`}
            </div>
          </div>
        )}

        <div ref={scrollRef} className="hud-panel flex-1 overflow-auto rounded border border-line p-4">
          {convLoading && messages.length === 0 && <PageLoading label="Loading conversation…" />}
          {!convLoading && messages.length === 0 && !live && (
            <div className="kai-metadata">
              Ask KAI a security question — e.g. “Inspect the public security headers of example.com”,
              “Which assessment tools are installed?”, or “Research advisories for openssl 3.0.2”.
            </div>
          )}
          {messages.map((m) => <MessageBubble key={m.id} m={m} onPick={pickCapability} />)}
          {faceBusy && (
            <div className="mb-4 rounded border border-line bg-panel-2 p-3">
              <div className="flex flex-wrap gap-4">
                {facePreview && (
                  <div className="shrink-0">
                    <div className="kai-metadata mb-1" style={{ color: "var(--kai-hud)" }}>● query image</div>
                    <div className="hud-frame overflow-hidden rounded border" style={{ borderColor: "var(--kai-hud-dim)" }}>
                      <img src={facePreview} alt="query" className="h-44 w-44 object-cover" />
                    </div>
                  </div>
                )}
                <div className="min-w-0 flex-1">
                  <ScanningStrip crops={scanCrops} label="scanning face index…" count={25} size={44} columns={5} />
                </div>
              </div>
            </div>
          )}
          {showRetry && (
            <button onClick={retryLast}
              className="mb-4 flex items-center gap-2 rounded border border-line px-3 py-1.5 text-sm hover:bg-panel">
              <RefreshCw size={14} /> Retry
            </button>
          )}
          {live && (
            <div className="mb-4">
              <div className="kai-metadata mb-1">KAI</div>
              {live.agentInfo?.map((a, i) => (
                <div key={i} className="kai-metadata mb-1">
                  {AGENT_LABELS[a.agent] ?? a.agent} · {a.reason}
                </div>
              ))}
              {live.tools.map((t, i) => <ToolCard key={i} t={t} />)}
              {live.pending && <ApprovalCard pending={live.pending} onDecide={decide} busy={deciding} />}
              {live.content && (
                <div className="inline-block max-w-full rounded bg-panel px-3 py-2 text-sm">
                  <Markdown>{live.content}</Markdown>
                </div>
              )}
              {live.thinking && !live.content && (
                <div className="kai-metadata animate-pulse">KAI is working… (local model inference can take a while)</div>
              )}
              {live.findings.map((f, i) => <FindingCard key={i} f={f} />)}
              {live.error && <div className="text-xs" style={{ color: "var(--kai-accent)" }}>⚠ {live.error}</div>}
            </div>
          )}
        </div>

        <div className="mt-3 flex items-end gap-2">
          <div className="relative flex-1">
            <span className="hud-mono pointer-events-none absolute left-3 top-2.5 text-xs" style={{ color: "var(--kai-hud)" }}>&gt;_</span>
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
              rows={2}
              placeholder="Message KAI…  (pick a capability on the right to scaffold a command)"
              className="w-full resize-none rounded border border-line bg-panel-2 py-2 pl-9 pr-3 text-sm outline-none focus:border-current"
              style={{ color: "inherit" }}
            />
          </div>
          <div className="flex overflow-hidden rounded border border-line" title="Where to search an uploaded face — pick either or both (both = fuller coverage)">
            <button onClick={() => setScopeDb((v) => !v)}
              className="px-2 py-2.5 text-[11px] hud-mono"
              style={scopeDb ? { background: "rgba(34,211,238,0.10)", color: "var(--kai-hud)" } : { color: "var(--kai-muted)" }}>
              DB
            </button>
            <button onClick={() => setScopeWeb((v) => !v)}
              className="border-l border-line px-2 py-2.5 text-[11px] hud-mono"
              style={scopeWeb ? { background: "rgba(34,211,238,0.10)", color: "var(--kai-hud)" } : { color: "var(--kai-muted)" }}>
              Web
            </button>
          </div>
          <input ref={imgInputRef} type="file" accept="image/*" className="hidden"
            onChange={(e) => { const f = e.target.files?.[0]; if (f) onImage(f); e.target.value = ""; }} />
          <button onClick={() => imgInputRef.current?.click()} disabled={faceBusy}
            title="Attach an image — KAI runs a face search"
            className="flex items-center rounded border border-line px-3 py-2.5 text-sm hover:bg-panel disabled:opacity-40"
            style={{ color: "var(--kai-muted)" }}>
            {faceBusy ? <Spinner size={15} /> : <ImagePlus size={15} />}
          </button>
          <button onClick={() => setShowCamera(true)} disabled={faceBusy}
            title="Live camera — capture a frame and run a face search"
            className="flex items-center rounded border border-line px-3 py-2.5 text-sm hover:bg-panel disabled:opacity-40"
            style={{ color: "var(--kai-muted)" }}>
            <Camera size={15} />
          </button>
          {voice.supported && (
            <button onClick={toggleMic}
              title={voice.listening ? "Stop listening" : wakeOn ? "Listen for “KAI …”" : "Talk to KAI"}
              className="flex items-center rounded border px-3 py-2.5 text-sm hover:bg-panel"
              style={{ borderColor: voice.listening ? "var(--kai-accent)" : "var(--kai-border)", color: voice.listening ? "var(--kai-accent)" : "var(--kai-muted)" }}>
              <Mic size={15} className={voice.listening ? "animate-pulse" : ""} />
            </button>
          )}
          {streaming ? (
            <button onClick={cancel} className="flex items-center gap-1 rounded border border-line px-3 py-2.5 text-sm hover:bg-panel" style={{ color: "var(--kai-accent)" }}>
              <Square size={14} /> Stop
            </button>
          ) : (
            <button onClick={() => send()} disabled={!input.trim()}
              className="flex items-center gap-1 rounded border px-3 py-2.5 text-sm hover:bg-panel disabled:opacity-40"
              style={{ borderColor: input.trim() ? "var(--kai-hud-dim)" : "var(--kai-border)", color: input.trim() ? "var(--kai-hud)" : undefined }}>
              <Send size={14} /> Send
            </button>
          )}
        </div>
      </div>

      {/* Action Deck — session controls, capability palette, live activity, assets */}
      <div className="hidden lg:flex">
        <ActionDeck
          status={status}
          selectedModel={selectedModel}
          onModelChange={changeModel}
          useTools={useTools}
          onUseToolsChange={setUseTools}
          autoApprove={autoApprove}
          onAutoApproveChange={setAutoApprove}
          think={think}
          onThinkChange={(v) => {
            setThink(v);
            try { if (activeId) localStorage.setItem(`kai.think.${activeId}`, v ? "1" : "0"); } catch { /* storage blocked */ }
          }}
          agent={agent}
          onAgentChange={setAgent}
          voiceSupported={voice.supported}
          wake={wakeOn}
          onWakeChange={changeWake}
          speak={speakOn}
          onSpeakChange={setSpeakOn}
          runs={runs}
          conversations={conversations}
          onOpenRun={openConversation}
          onStopRun={stopRun}
          stopping={stopping}
          onPick={pickCapability}
          activeId={activeId}
        />
      </div>

      {showCamera && (
        <CameraCapture onClose={() => setShowCamera(false)} onCapture={(f) => onImage(f)} />
      )}
    </div>
  );
}
