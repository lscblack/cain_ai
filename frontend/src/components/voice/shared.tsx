import { useEffect, useRef, useState, type ReactNode } from "react";
import { Download } from "lucide-react";

import { Spinner } from "@/components/Async";
import { fetchVoiceAudio, LANGUAGES, type VoiceProfile, voiceError } from "@/lib/voice";

export const inputCls = "w-full border border-line bg-panel px-3 py-2 text-sm outline-none focus:border-[color:var(--kai-hud)]";
export const selectCls = "w-full rounded border border-line bg-panel-2 px-2 py-2 text-sm";
export const primaryBtnCls = "hud-mono border px-4 py-2 text-sm uppercase tracking-wider transition hover:brightness-125 disabled:opacity-40";
export const btnCls = "flex items-center gap-1 rounded border border-line px-2 py-1 text-xs hover:bg-panel disabled:opacity-40";
export const primaryStyle = { borderColor: "var(--kai-hud-dim)", color: "var(--kai-hud)" };

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="kai-metadata mb-1 block">{label}</span>
      {children}
      {hint && <span className="kai-metadata mt-1 block">{hint}</span>}
    </label>
  );
}

export function SectionTitle({ children, inline = false }: { children: ReactNode; inline?: boolean }) {
  return <h2 className={`hud-mono uppercase text-xs ${inline ? "" : "mb-3"}`} style={{ color: "var(--kai-hud)" }}>◢ {children}</h2>;
}

export function ErrorLine({ error }: { error: string | null }) {
  if (!error) return null;
  return <div className="mb-4 text-sm" style={{ color: "var(--kai-accent)" }}>{error}</div>;
}

const STATUS_COLOR: Record<string, string> = {
  ready: "var(--kai-verified)", completed: "var(--kai-verified)", installed: "var(--kai-verified)",
  processing: "var(--kai-hud)", running: "var(--kai-hud)", queued: "var(--kai-hud)", installing: "var(--kai-hud)",
  failed: "var(--kai-accent)", canceled: "var(--kai-muted)", not_installed: "var(--kai-muted)", draft: "var(--kai-muted)",
};

export function StatusTag({ status, label }: { status: string; label?: string }) {
  const color = STATUS_COLOR[status] ?? "var(--kai-muted)";
  return (
    <span className="kai-metadata inline-flex items-center gap-1.5 uppercase" style={{ color }}>
      <span className="inline-block h-1.5 w-1.5 rounded-full" style={{ background: color }} />
      {label ?? status.replace(/_/g, " ")}
    </span>
  );
}

export function Meter({ value, label }: { value: number; label: string }) {
  const pct = Math.min(100, Math.sqrt(Math.max(0, value)) * 100);
  return (
    <div>
      <div className="kai-metadata mb-1 flex justify-between"><span>{label}</span><span>{pct.toFixed(0)}%</span></div>
      <div className="hud-bar"><span style={{ width: `${pct}%`, transition: "width 60ms linear" }} /></div>
    </div>
  );
}

export function LanguageSelect({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)} className={selectCls}>
      {LANGUAGES.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
    </select>
  );
}

export function VoiceSelect({ voices, value, onChange, onlyReady = true }: {
  voices: VoiceProfile[]; value: string; onChange: (v: string) => void; onlyReady?: boolean;
}) {
  const list = onlyReady ? voices.filter((v) => v.status === "ready") : voices;
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)} className={selectCls}>
      {list.length === 0 && <option value="">No ready voices</option>}
      {list.map((v) => <option key={v.id} value={v.id}>{v.name}{v.is_default ? " (default)" : ""}</option>)}
    </select>
  );
}

/** Player for an authenticated audio route. Fetches only once the operator asks to listen. */
export function AuthAudio({ path }: { path: string }) {
  const [src, setSrc] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(true);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const blob = await fetchVoiceAudio(path);
      if (mounted.current) setSrc(URL.createObjectURL(blob));
    } catch (e) {
      if (mounted.current) setError(voiceError(e));
    } finally {
      if (mounted.current) setLoading(false);
    }
  }

  useEffect(() => () => { if (src) URL.revokeObjectURL(src); }, [src]);
  useEffect(() => () => { mounted.current = false; }, []);

  if (src) return <audio src={src} controls className="h-9 w-full" />;
  if (loading) return <Spinner label="Loading audio…" />;
  return (
    <div className="flex items-center gap-2">
      <button onClick={load} className={btnCls}>Listen</button>
      {error && <span className="kai-metadata" style={{ color: "var(--kai-accent)" }}>{error}</span>}
    </div>
  );
}

export function DownloadAudio({ path, filename, label }: { path: string; filename: string; label: string }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function run() {
    setBusy(true);
    setError(null);
    try {
      const url = URL.createObjectURL(await fetchVoiceAudio(path));
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 10_000);
    } catch (e) {
      setError(voiceError(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <button onClick={run} disabled={busy} className={btnCls}><Download size={12} /> {label}</button>
      {error && <span className="kai-metadata" style={{ color: "var(--kai-accent)" }}>{error}</span>}
    </>
  );
}

export function formatDuration(seconds: number): string {
  if (!seconds) return "0:00";
  const s = Math.round(seconds);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export function formatDate(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString() : "—";
}

export function ConsentFields({ value, onChange }: {
  value: { confirmed: boolean; basis: string; subject: string };
  onChange: (v: { confirmed: boolean; basis: string; subject: string }) => void;
}) {
  return (
    <div className="space-y-3 border p-3" style={{ borderColor: "var(--kai-warn)" }}>
      <div className="kai-metadata" style={{ color: "var(--kai-warn)" }}>Consent required</div>
      <div className="space-y-2 text-sm">
        <label className="flex items-center gap-2">
          <input type="radio" checked={value.basis === "own_voice"} onChange={() => onChange({ ...value, basis: "own_voice", subject: "" })} />
          This is my own voice
        </label>
        <label className="flex items-center gap-2">
          <input type="radio" checked={value.basis === "permission"} onChange={() => onChange({ ...value, basis: "permission" })} />
          This person gave me explicit permission
        </label>
      </div>
      {value.basis === "permission" && (
        <Field label="Who gave permission">
          <input value={value.subject} maxLength={200} onChange={(e) => onChange({ ...value, subject: e.target.value })} className={inputCls} />
        </Field>
      )}
      <label className="flex items-start gap-2 text-sm">
        <input type="checkbox" className="mt-1" checked={value.confirmed} onChange={(e) => onChange({ ...value, confirmed: e.target.checked })} />
        <span>I have the right to clone this voice, and I won't use it to deceive anyone, impersonate someone without their authorization, or get past voice authentication.</span>
      </label>
    </div>
  );
}

export function consentForm(form: FormData, c: { confirmed: boolean; basis: string; subject: string }) {
  form.set("consent_confirmed", String(c.confirmed));
  form.set("consent_basis", c.basis);
  form.set("consent_subject", c.subject);
}

export const consentOk = (c: { confirmed: boolean; basis: string; subject: string }) =>
  c.confirmed && (c.basis === "own_voice" || (c.basis === "permission" && !!c.subject.trim()));
