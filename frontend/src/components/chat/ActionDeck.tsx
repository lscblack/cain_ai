import { useCallback, useEffect, useState, type ReactNode } from "react";
import {
  Cpu, Wrench, Zap, Brain, ChevronDown, Activity, FolderOpen, Download, Trash2,
  RefreshCw, Square, Command, ScrollText, Loader2, Network, Radio, Volume2, GraduationCap,
} from "lucide-react";
import {
  chatApi, type ModelStatus, type Conversation, type ActiveRun, type KaiAsset,
} from "@/lib/chat";
import { CapabilityPalette } from "@/components/chat/CapabilityPalette";
import { humanSize, downloadKaiFile } from "@/components/chat/util";
import { Markdown } from "@/components/Markdown";

interface Props {
  status: ModelStatus | null;
  selectedModel: string;
  onModelChange: (m: string) => void;
  useTools: boolean;
  onUseToolsChange: (v: boolean) => void;
  autoApprove: boolean;
  onAutoApproveChange: (v: boolean) => void;
  think: boolean;
  onThinkChange: (v: boolean) => void;
  multi: boolean;
  onMultiChange: (v: boolean) => void;
  voiceSupported: boolean;
  wake: boolean;
  onWakeChange: (v: boolean) => void;
  speak: boolean;
  onSpeakChange: (v: boolean) => void;
  runs: ActiveRun[];
  conversations: Conversation[];
  onOpenRun: (convId: string) => void;
  onStopRun: (convId: string) => void;
  stopping: Set<string>;
  onPick: (text: string) => void;
  activeId: string | null;
}

function Section({ icon: Icon, title, badge, defaultOpen = true, grow = false, children }: {
  icon: typeof Zap; title: string; badge?: ReactNode; defaultOpen?: boolean; grow?: boolean; children: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className={`flex flex-col rounded border border-line bg-panel ${grow && open ? "min-h-0 flex-1" : ""}`}>
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 px-2.5 py-2 text-left"
      >
        <Icon size={13} style={{ color: "var(--kai-hud)" }} />
        <span className="hud-mono text-[11px] uppercase tracking-wider" style={{ color: "var(--kai-hud)" }}>{title}</span>
        {badge}
        <ChevronDown
          size={14}
          className={`ml-auto text-muted transition-transform ${open ? "" : "-rotate-90"}`}
        />
      </button>
      {open && <div className="flex min-h-0 flex-col px-2.5 pb-2.5">{children}</div>}
    </div>
  );
}

function Toggle({ checked, onChange, icon: Icon, label, hint }: {
  checked: boolean; onChange: (v: boolean) => void; icon: typeof Zap; label: string; hint: string;
}) {
  return (
    <button
      onClick={() => onChange(!checked)}
      title={hint}
      className="flex items-center gap-2 rounded border px-2 py-1.5 text-left text-xs transition-colors"
      style={{
        borderColor: checked ? "var(--kai-hud-dim)" : "var(--kai-border)",
        background: checked ? "rgba(34,211,238,0.06)" : "transparent",
        color: checked ? "var(--kai-hud)" : "var(--kai-muted)",
      }}
    >
      <Icon size={13} />
      <span className="flex-1">{label}</span>
      <span className="hud-mono text-[10px]">{checked ? "ON" : "OFF"}</span>
    </button>
  );
}

export function ActionDeck(p: Props) {
  const [assets, setAssets] = useState<KaiAsset[]>([]);
  const [assetsLoading, setAssetsLoading] = useState(false);
  const [summary, setSummary] = useState("");
  const [summaryBusy, setSummaryBusy] = useState(false);
  const [summaryErr, setSummaryErr] = useState<string | null>(null);
  const [learnBusy, setLearnBusy] = useState(false);
  const [learnMsg, setLearnMsg] = useState<string | null>(null);
  const s = p.status;

  async function learnFromSession() {
    if (!p.activeId) { setLearnMsg("Open a conversation first."); return; }
    setLearnBusy(true); setLearnMsg(null);
    try {
      const r = await chatApi.learnProfile(p.activeId);
      setLearnMsg(`Profile updated (${r.char_count} chars). KAI will adapt to how you work.`);
    } catch (e: any) { setLearnMsg(e?.message || "Learn failed"); }
    finally { setLearnBusy(false); }
  }

  useEffect(() => { setSummary(""); setSummaryErr(null); }, [p.activeId]);

  async function genSummary() {
    if (!p.activeId) { setSummaryErr("Open a conversation first."); return; }
    setSummaryBusy(true); setSummaryErr(null);
    try { setSummary((await chatApi.summarize(p.activeId)).summary); }
    catch (e: any) { setSummaryErr(e?.message || "Summary failed"); }
    finally { setSummaryBusy(false); }
  }

  const loadAssets = useCallback(async () => {
    setAssetsLoading(true);
    try { setAssets((await chatApi.assets()).files); } catch { setAssets([]); }
    finally { setAssetsLoading(false); }
  }, []);
  useEffect(() => { loadAssets(); }, [loadAssets]);

  async function removeAsset(id: string) {
    try { await chatApi.deleteAsset(id); setAssets((a) => a.filter((f) => f.id !== id)); } catch { /* */ }
  }

  const modelColor = s?.ready ? "var(--kai-verified)" : "var(--kai-accent)";

  return (
    <div className="flex min-h-0 w-72 shrink-0 flex-col gap-2 overflow-auto">
      {/* Session */}
      <Section icon={Cpu} title="Session" badge={
        <span className="hud-mono text-[10px]" style={{ color: modelColor }}>
          ● {s ? (s.ready ? "ready" : s.reachable ? "loading" : "offline") : "…"}
        </span>
      }>
        <label className="mb-2 flex flex-col gap-1">
          <span className="kai-metadata">model</span>
          <select
            value={p.selectedModel}
            onChange={(e) => p.onModelChange(e.target.value)}
            className="rounded border border-line bg-panel-2 px-2 py-1 text-xs outline-none focus:border-current"
            style={{ color: "inherit" }}
          >
            {p.selectedModel && !(s?.models_available ?? []).some((m) => m === p.selectedModel) && (
              <option value={p.selectedModel}>{p.selectedModel}</option>
            )}
            {(s?.models_available ?? []).map((m) => {
              const be = s?.models_detail?.find((d) => d.name === m)?.backend;
              return <option key={m} value={m}>{m}{be ? ` · ${be === "llamacpp" ? "llama.cpp" : "ollama"}` : ""}</option>;
            })}
          </select>
        </label>
        <div className="grid gap-1.5">
          <Toggle checked={p.useTools} onChange={p.onUseToolsChange} icon={Wrench}
            label="Tools" hint="Let KAI select and run real tools" />
          {p.useTools && (
            <Toggle checked={p.autoApprove} onChange={p.onAutoApproveChange} icon={Zap}
              label="Auto-run" hint="Skip the Go-ahead prompt and run tools immediately" />
          )}
          <Toggle checked={p.think} onChange={p.onThinkChange} icon={Brain}
            label="Think" hint="Qwen3 reasoning: more accurate, slower on CPU" />
          <Toggle checked={p.multi} onChange={p.onMultiChange} icon={Network}
            label="Multi-agent" hint="Split a big task into subtasks and run a focused sub-agent on each (sequential)" />
          {p.voiceSupported && <>
            <Toggle checked={p.wake} onChange={p.onWakeChange} icon={Radio}
              label="Wake word" hint="When listening, only act on utterances that start with “KAI …”" />
            <Toggle checked={p.speak} onChange={p.onSpeakChange} icon={Volume2}
              label="Speak replies" hint="Read KAI's answers aloud (text-to-speech)" />
          </>}
        </div>
      </Section>

      {/* Capabilities palette */}
      <Section icon={Command} title="Capabilities" grow defaultOpen>
        <p className="kai-metadata mb-2">Click to scaffold a prompt — edit the blanks, then send.</p>
        <CapabilityPalette onPick={p.onPick} />
      </Section>

      {/* Live activity */}
      <Section icon={Activity} title="Activity" badge={
        p.runs.length ? <span className="h-1.5 w-1.5 animate-pulse rounded-full" style={{ background: "var(--kai-hud)" }} /> : undefined
      } defaultOpen={p.runs.length > 0}>
        {p.runs.length === 0 && <div className="kai-metadata py-1">Nothing running.</div>}
        <div className="space-y-1">
          {p.runs.map((r) => {
            const title = p.conversations.find((c) => c.id === r.conversation_id)?.title || "conversation";
            const busy = p.stopping.has(r.conversation_id);
            return (
              <div key={r.conversation_id} className="flex items-center gap-1.5 rounded border border-line bg-panel-2 px-1.5 py-1.5">
                <button onClick={() => p.onOpenRun(r.conversation_id)} className="flex min-w-0 flex-1 flex-col text-left">
                  <span className="truncate text-[11px]">{title}</span>
                  <span className="kai-metadata truncate">
                    <span style={{ color: "var(--kai-hud)" }}>● {r.activity || "thinking"}</span> · {r.seconds}s
                  </span>
                </button>
                <button onClick={() => p.onStopRun(r.conversation_id)} disabled={busy}
                  className="flex items-center gap-1 rounded border border-line px-1.5 py-1 text-[10px] hover:bg-panel disabled:opacity-40"
                  style={{ color: "var(--kai-accent)" }} title="Stop this one">
                  <Square size={10} /> {busy ? "…" : "stop"}
                </button>
              </div>
            );
          })}
        </div>
      </Section>

      {/* Assets */}
      <Section icon={FolderOpen} title="Assets" badge={<span className="kai-metadata">{assets.length}</span>} defaultOpen={false}>
        <div className="mb-1.5 flex items-center justify-between">
          <span className="kai-metadata">Files KAI created.</span>
          <button onClick={loadAssets} className="kai-metadata hover:text-ink" title="Refresh"><RefreshCw size={12} /></button>
        </div>
        {assetsLoading && <div className="kai-metadata py-1">Loading…</div>}
        {!assetsLoading && assets.length === 0 && <div className="kai-metadata py-1">No assets yet.</div>}
        <div className="space-y-1">
          {assets.map((f) => (
            <div key={f.id} className="flex items-center gap-1.5 rounded border border-line bg-panel-2 px-1.5 py-1.5">
              <button onClick={() => downloadKaiFile(f)} className="flex min-w-0 flex-1 items-center gap-1.5 text-left" title={`Download ${f.name}`}>
                <Download size={12} style={{ color: "var(--kai-hud)" }} />
                <span className="hud-mono truncate text-[11px]">{f.name}</span>
              </button>
              <span className="kai-metadata whitespace-nowrap">{humanSize(f.size)}</span>
              <button onClick={() => removeAsset(f.id)} className="text-muted hover:text-ink" title="Delete"><Trash2 size={12} /></button>
            </div>
          ))}
        </div>
      </Section>

      {/* Session summary — generated on demand */}
      <Section icon={ScrollText} title="Session summary" defaultOpen={false}>
        <button onClick={genSummary} disabled={summaryBusy}
          className="mb-2 flex items-center justify-center gap-2 rounded border px-2 py-1.5 text-xs hover:bg-panel-2 disabled:opacity-40"
          style={{ borderColor: "var(--kai-hud-dim)", color: "var(--kai-hud)" }}>
          {summaryBusy ? <Loader2 size={13} className="kai-spin" /> : <ScrollText size={13} />}
          {summaryBusy ? "Summarizing…" : summary ? "Regenerate summary" : "Summarize session"}
        </button>
        {summaryErr && <div className="text-[11px]" style={{ color: "var(--kai-accent)" }}>{summaryErr}</div>}
        {summary && (
          <div className="max-h-72 overflow-auto rounded border border-line bg-panel-2 p-2 text-xs">
            <Markdown>{summary}</Markdown>
          </div>
        )}
        {!summary && !summaryErr && !summaryBusy && (
          <div className="kai-metadata">Recap of objectives, actions, findings and next steps.</div>
        )}
      </Section>

      {/* Learn — KAI picks up how the operator works from this session */}
      <Section icon={GraduationCap} title="Teach KAI" defaultOpen={false}>
        <button onClick={learnFromSession} disabled={learnBusy}
          className="mb-1.5 flex items-center justify-center gap-2 rounded border px-2 py-1.5 text-xs hover:bg-panel-2 disabled:opacity-40"
          style={{ borderColor: "var(--kai-hud-dim)", color: "var(--kai-hud)" }}>
          {learnBusy ? <Loader2 size={13} className="kai-spin" /> : <GraduationCap size={13} />}
          {learnBusy ? "Learning…" : "Learn from this session"}
        </button>
        {learnMsg && <div className="text-[11px]" style={{ color: learnMsg.startsWith("Profile") ? "var(--kai-verified)" : "var(--kai-accent)" }}>{learnMsg}</div>}
        <div className="kai-metadata mt-1">KAI extracts how you work and applies it to every chat. Edit it on the Skills page.</div>
      </Section>
    </div>
  );
}
