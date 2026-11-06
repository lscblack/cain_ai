import { useEffect, useState } from "react";
import { Activity, Download, Power, RefreshCw } from "lucide-react";

import { AsyncBoundary, useAsync } from "@/components/Async";
import { friendly, voiceApi, voiceError, type VoiceHardware, type VoiceModel } from "@/lib/voice";
import { btnCls, ErrorLine, SectionTitle, StatusTag } from "@/components/voice/shared";

const KIND_LABEL: Record<string, string> = { tts: "Text-to-Speech", vc: "Live Voice Changer", asr: "Transcription", vad: "Voice activity" };

function HardwarePanel({ hw, onProbe, probing }: { hw: VoiceHardware; onProbe: () => void; probing: boolean }) {
  const gpuOk = hw.gpu.torch?.cuda_available;
  return (
    <div className="hud-panel hud-frame mb-4 p-4">
      <div className="mb-2 flex items-center justify-between">
        <SectionTitle inline>Hardware</SectionTitle>
        <button className={btnCls} disabled={probing} onClick={onProbe}><RefreshCw size={12} /> {probing ? "Testing…" : "Test GPU in PyTorch"}</button>
      </div>
      <div className="mb-3 text-sm" style={{ color: hw.selected_device === "cuda" ? "var(--kai-verified)" : "var(--kai-warn)" }}>{hw.summary}</div>
      <div className="grid gap-x-6 gap-y-1 md:grid-cols-2">
        <div className="kai-metadata">CPU: {hw.cpu.model} ({hw.cpu.threads} threads)</div>
        <div className="kai-metadata">RAM: {hw.ram.available_gb} GB free of {hw.ram.total_gb} GB</div>
        <div className="kai-metadata">Disk free for voice data: {hw.disk_free_gb} GB</div>
        <div className="kai-metadata">GPU: {hw.gpu.name || hw.gpu.pci_name || "None found"}</div>
        <div className="kai-metadata">NVIDIA driver: {hw.gpu.driver_loaded ? hw.gpu.driver_version : "Not loaded"}</div>
        <div className="kai-metadata">nvidia-smi: {hw.gpu.smi_ok ? `${hw.gpu.vram_free_mb} MB free of ${hw.gpu.vram_total_mb} MB` : hw.gpu.smi_message}</div>
        <div className="kai-metadata">CUDA in PyTorch: {hw.gpu.torch ? (gpuOk ? "Available" : `Unavailable${hw.gpu.torch.error ? ` (${hw.gpu.torch.error})` : ""}`) : "Not tested yet"}</div>
      </div>
    </div>
  );
}

function ModelCard({ m, onAction, busy }: { m: VoiceModel; onAction: (id: string, a: "install" | "load" | "unload" | "health") => void; busy: boolean }) {
  const installing = m.install?.state === "running";
  return (
    <div className="hud-panel hud-frame p-4">
      <div className="mb-1 flex items-start justify-between gap-2">
        <div>
          <div className="text-sm font-semibold">{m.name}</div>
          <div className="kai-metadata">{KIND_LABEL[m.kind]} · {m.license}{m.optional ? " · Optional" : ""}</div>
        </div>
        <StatusTag status={installing ? "installing" : m.installed ? "installed" : "not_installed"} label={m.loaded ? `Loaded on ${m.device}` : undefined} />
      </div>
      <p className="my-2 text-sm text-muted">{m.description}</p>
      <div className="kai-metadata space-y-0.5">
        <div>Version: {m.revision ? m.revision.slice(0, 12) : "—"} · Download: {m.download_gb} GB · Needs {m.min_ram_gb} GB RAM</div>
        {m.installed && <div className="break-all">Stored in: {m.location}</div>}
        <div className="break-all">Environment: {m.env_path} {m.env_ready ? "" : "(not created)"}</div>
        <a className="underline" href={m.repo_url} target="_blank" rel="noreferrer">Source</a>
      </div>
      {!m.compatibility.ok && <div className="mt-2 text-sm" style={{ color: "var(--kai-warn)" }}>{m.compatibility.notes.join(" ")}</div>}
      {m.compatibility.ok && m.compatibility.notes.length > 0 && <div className="kai-metadata mt-2" style={{ color: "var(--kai-warn)" }}>{m.compatibility.notes.join(" ")}</div>}
      {m.realtime && <div className="kai-metadata mt-2">Measured here: {m.realtime.summary}</div>}
      {m.health?.ok !== undefined && (
        <div className="kai-metadata mt-2" style={{ color: m.health.ok ? "var(--kai-verified)" : "var(--kai-accent)" }}>
          Health check: {m.health.ok ? `passed in ${m.health.seconds}s on ${m.health.device}` : m.health.error}
        </div>
      )}
      {m.install && m.install.state !== "idle" && (
        <div className="mt-3">
          <div className="kai-metadata mb-1">{m.install.step}</div>
          {installing && <div className="hud-bar"><span style={{ width: `${Math.max(2, m.install.progress * 100)}%` }} /></div>}
          {m.install.error && <pre className="mt-2 max-h-32 overflow-auto whitespace-pre-wrap text-xs" style={{ color: "var(--kai-accent)" }}>{m.install.error}</pre>}
        </div>
      )}
      <div className="mt-3 flex flex-wrap gap-2">
        {!m.installed && <button className={btnCls} disabled={busy || installing || !m.compatibility.ok} onClick={() => onAction(m.id, "install")}><Download size={12} /> Install</button>}
        {m.installed && m.kind !== "vad" && !m.loaded && <button className={btnCls} disabled={busy} onClick={() => onAction(m.id, "load")}><Power size={12} /> Load</button>}
        {m.loaded && <button className={btnCls} disabled={busy} onClick={() => onAction(m.id, "unload")}><Power size={12} /> Unload</button>}
        {m.installed && <button className={btnCls} disabled={busy} onClick={() => onAction(m.id, "health")}><Activity size={12} /> Run health check</button>}
      </div>
    </div>
  );
}

export function Models() {
  const models = useAsync(friendly(() => voiceApi.models().then((r) => r.models)), []);
  const hardware = useAsync(friendly(() => voiceApi.hardware()), []);
  const [busy, setBusy] = useState(false);
  const [probing, setProbing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const installing = models.data?.some((m) => m.install?.state === "running");
  useEffect(() => {
    if (!installing) return;
    const t = window.setInterval(() => voiceApi.models().then((r) => models.setData(r.models)).catch(() => undefined), 1500);
    return () => window.clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [installing]);

  async function action(id: string, a: "install" | "load" | "unload" | "health") {
    setBusy(true);
    setError(null);
    try {
      await voiceApi.modelAction(id, a);
      models.retry();
    } catch (e) {
      setError(voiceError(e));
    } finally {
      setBusy(false);
    }
  }

  async function probe() {
    setProbing(true);
    setError(null);
    try {
      hardware.setData(await voiceApi.hardware(true));
    } catch (e) {
      setError(voiceError(e));
    } finally {
      setProbing(false);
    }
  }

  return (
    <div>
      <ErrorLine error={error} />
      <AsyncBoundary state={hardware} loadingLabel="Checking hardware…">
        {(hw) => <HardwarePanel hw={hw} onProbe={probe} probing={probing} />}
      </AsyncBoundary>
      <AsyncBoundary state={models} loadingLabel="Loading models…">
        {(rows) => (
          <div className="grid gap-3 md:grid-cols-2">
            {rows.map((m) => <ModelCard key={m.id} m={m} onAction={action} busy={busy} />)}
          </div>
        )}
      </AsyncBoundary>
    </div>
  );
}
