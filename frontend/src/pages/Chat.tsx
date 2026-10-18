import { useCallback, useEffect, useRef, useState } from "react";
import {
  MessageSquare, Plus, Trash2, Send, Square, Wrench, AlertTriangle, Cpu, RefreshCw,
} from "lucide-react";

import {
  chatApi, streamMessage, type Conversation, type ChatMessage, type ModelStatus, type Finding,
} from "@/lib/chat";
import { PageLoading } from "@/components/Async";

interface ToolEvent {
  operation: string;
  params?: any;
  result?: any;
}
interface LiveTurn {
  content: string;
  tools: ToolEvent[];
  findings: Finding[];
  error: string | null;
  thinking: boolean;
}

const SEV_COLOR: Record<string, string> = {
  critical: "var(--kai-accent)", high: "var(--kai-accent)", medium: "#f59e0b",
  low: "var(--kai-hud)", info: "var(--kai-hud)",
};

function ModelBadge({ status }: { status: ModelStatus | null }) {
  if (!status) return <span className="kai-metadata">checking model…</span>;
  const ok = status.ready;
  const color = ok ? "var(--kai-verified)" : "var(--kai-accent)";
  return (
    <div className="flex items-center gap-2" title={status.error || status.endpoint}>
      <Cpu size={14} style={{ color }} />
      <span className="hud-mono text-xs" style={{ color }}>
        {status.model} · {ok ? "ready" : status.reachable ? "model missing" : "offline"}
      </span>
    </div>
  );
}

function ToolCard({ t }: { t: ToolEvent }) {
  const r = t.result || {};
  const status = r.status || (r.ok ? "ok" : "…");
  const color = r.ok ? "var(--kai-verified)" : status === "denied" || status === "blocked" ? "#f59e0b" : "var(--kai-accent)";
  const out = (r.stdout || "") + (r.stderr ? "\n" + r.stderr : "");
  return (
    <div className="my-2 rounded border border-line bg-panel-2 p-2 text-xs">
      <div className="flex items-center gap-2">
        <Wrench size={12} style={{ color: "var(--kai-hud)" }} />
        <span className="hud-mono" style={{ color: "var(--kai-hud)" }}>{t.operation}</span>
        <span className="hud-mono" style={{ color }}>● {status}</span>
        {r.posture && <span className="kai-metadata uppercase">{r.posture}</span>}
      </div>
      {t.params && Object.keys(t.params).length > 0 && (
        <div className="kai-metadata mt-1">{Object.entries(t.params).map(([k, v]) => `${k}=${v}`).join("  ")}</div>
      )}
      {(r.message || r.error) && <div className="mt-1" style={{ color }}>{r.message || r.error}</div>}
      {out.trim() && (
        <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap break-words font-mono text-[11px] text-muted">{out.trim()}</pre>
      )}
      {r.result && (
        <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap break-words font-mono text-[11px] text-muted">{JSON.stringify(r.result, null, 2)}</pre>
      )}
    </div>
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
        <span className="kai-metadata">· {f.confidence} · {f.status}</span>
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

function MessageBubble({ m }: { m: ChatMessage }) {
  const isUser = m.role === "user";
  const findings: Finding[] = m.meta?.findings || [];
  return (
    <div className={`mb-4 ${isUser ? "text-right" : ""}`}>
      <div className="kai-metadata mb-1">{isUser ? "OPERATOR" : "KAI"}</div>
      <div className={`inline-block max-w-full rounded px-3 py-2 text-sm ${isUser ? "bg-panel-2" : "bg-panel"}`}>
        <div className="whitespace-pre-wrap break-words text-left">{m.content}</div>
      </div>
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
  const [useTools, setUseTools] = useState(true);
  const [live, setLive] = useState<LiveTurn | null>(null);
  const [streaming, setStreaming] = useState(false);
  const [convLoading, setConvLoading] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const lastSentRef = useRef<string>("");

  const loadConversations = useCallback(async () => {
    try { setConversations(await chatApi.listConversations()); } catch { /* */ }
  }, []);

  useEffect(() => {
    chatApi.status().then(setStatus).catch(() => setStatus(null));
    loadConversations();
    const id = setInterval(() => chatApi.status().then(setStatus).catch(() => {}), 15000);
    return () => clearInterval(id);
  }, [loadConversations]);

  const openConversation = useCallback(async (id: string) => {
    setActiveId(id);
    setLive(null);
    setConvLoading(true);
    try {
      const detail = await chatApi.getConversation(id);
      setMessages(detail.messages);
    } catch { setMessages([]); }
    finally { setConvLoading(false); }
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, live]);

  async function newConversation() {
    const c = await chatApi.createConversation({});
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
    lastSentRef.current = content;
    let convId = activeId;
    if (!convId) {
      const c = await chatApi.createConversation({});
      convId = c.id;
      setActiveId(c.id);
      loadConversations();
    }
    if (forced === undefined) setInput("");
    setMessages((m) => [...m, {
      id: `local-${Date.now()}`, role: "user", content, tool_calls: null,
      tool_results: null, meta: {}, created_at: new Date().toISOString(),
    }]);
    const turn: LiveTurn = { content: "", tools: [], findings: [], error: null, thinking: true };
    setLive({ ...turn });
    setStreaming(true);
    const ctrl = new AbortController();
    abortRef.current = ctrl;

    try {
      await streamMessage(convId!, content, useTools, (e) => {
        if (e.event === "thinking") turn.thinking = true;
        else if (e.event === "tool_call") { turn.tools.push({ operation: e.data.operation, params: e.data.params }); turn.thinking = false; }
        else if (e.event === "tool_result") {
          const last = turn.tools[turn.tools.length - 1];
          if (last && last.operation === e.data.operation) last.result = e.data.result;
          else turn.tools.push({ operation: e.data.operation, result: e.data.result });
        } else if (e.event === "token") { turn.content += e.data.text; turn.thinking = false; }
        else if (e.event === "message" || e.event === "final") {
          turn.content = e.data.answer ?? e.data.content ?? turn.content;
          if (e.data.findings) turn.findings = e.data.findings;
          turn.thinking = false;
        } else if (e.event === "error") { turn.error = e.data.message || e.data.code; turn.thinking = false; }
        setLive({ ...turn, tools: [...turn.tools], findings: [...turn.findings] });
      }, ctrl.signal);
    } catch (err: any) {
      turn.error = err?.message || "stream failed";
    } finally {
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
      loadConversations();
    }
  }

  function cancel() {
    abortRef.current?.abort();
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
    <div className="flex h-[calc(100vh-7rem)] gap-4">
      {/* conversation history */}
      <aside className="hidden w-64 shrink-0 flex-col md:flex">
        <button onClick={newConversation}
          className="mb-2 flex items-center justify-center gap-2 rounded border border-line px-3 py-2 text-sm hover:bg-panel">
          <Plus size={14} /> New conversation
        </button>
        <div className="flex-1 space-y-1 overflow-auto">
          {conversations.map((c) => (
            <div key={c.id}
              className={`group flex items-center justify-between rounded px-2 py-2 text-sm cursor-pointer ${activeId === c.id ? "bg-panel" : "hover:bg-panel-2"}`}
              onClick={() => openConversation(c.id)}>
              <span className="truncate">{c.title}</span>
              <button onClick={(e) => { e.stopPropagation(); removeConversation(c.id); }}
                className="opacity-0 group-hover:opacity-100" title="Delete">
                <Trash2 size={13} className="text-muted hover:text-ink" />
              </button>
            </div>
          ))}
          {conversations.length === 0 && <div className="kai-metadata px-2">No conversations yet.</div>}
        </div>
      </aside>

      {/* main chat */}
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="mb-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <MessageSquare size={18} style={{ color: "var(--kai-hud)" }} />
            <h1 className="hud-mono hud-glow text-lg font-semibold" style={{ color: "var(--kai-hud)" }}>◢ KAI Chat</h1>
          </div>
          <ModelBadge status={status} />
        </div>

        {status && !status.ready && (
          <div className="mb-3 rounded border border-line bg-panel-2 p-3 text-xs" style={{ borderColor: "var(--kai-accent)" }}>
            <div className="flex items-center gap-2" style={{ color: "var(--kai-accent)" }}>
              <AlertTriangle size={14} /> Model not ready
            </div>
            <div className="mt-1 text-muted">
              {status.reachable
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
          {messages.map((m) => <MessageBubble key={m.id} m={m} />)}
          {showRetry && (
            <button onClick={retryLast}
              className="mb-4 flex items-center gap-2 rounded border border-line px-3 py-1.5 text-sm hover:bg-panel">
              <RefreshCw size={14} /> Retry
            </button>
          )}
          {live && (
            <div className="mb-4">
              <div className="kai-metadata mb-1">KAI</div>
              {live.tools.map((t, i) => <ToolCard key={i} t={t} />)}
              {live.content && (
                <div className="inline-block max-w-full rounded bg-panel px-3 py-2 text-sm">
                  <div className="whitespace-pre-wrap break-words">{live.content}</div>
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
          <label className="flex items-center gap-1 text-xs text-muted" title="Let KAI select and run real tools">
            <input type="checkbox" checked={useTools} onChange={(e) => setUseTools(e.target.checked)} />
            tools
          </label>
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
            rows={2}
            placeholder="Message KAI…"
            className="flex-1 resize-none rounded border border-line bg-panel-2 px-3 py-2 text-sm outline-none focus:border-current"
            style={{ color: "inherit" }}
          />
          {streaming ? (
            <button onClick={cancel} className="flex items-center gap-1 rounded border border-line px-3 py-2 text-sm hover:bg-panel" style={{ color: "var(--kai-accent)" }}>
              <Square size={14} /> Stop
            </button>
          ) : (
            <button onClick={() => send()} disabled={!input.trim()}
              className="flex items-center gap-1 rounded border border-line px-3 py-2 text-sm hover:bg-panel disabled:opacity-40">
              <Send size={14} /> Send
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
