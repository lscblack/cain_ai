import { useEffect, useState } from "react";
import { Play } from "lucide-react";

import { AsyncBoundary, useAsync } from "@/components/Async";
import { friendly, voiceApi, voiceError, type VoiceGeneration } from "@/lib/voice";
import { GenerationRow } from "@/components/voice/GenerationRow";
import {
  ErrorLine, Field, inputCls, LanguageSelect, primaryBtnCls, primaryStyle, SectionTitle, VoiceSelect,
} from "@/components/voice/shared";

function Slider({ label, value, min, max, step, onChange, unit = "", hint }: {
  label: string; value: number; min: number; max: number; step: number; onChange: (v: number) => void; unit?: string; hint?: string;
}) {
  return (
    <Field label={`${label}: ${value}${unit}`} hint={hint}>
      <input type="range" className="w-full" value={value} min={min} max={max} step={step} onChange={(e) => onChange(Number(e.target.value))} />
    </Field>
  );
}

export function TtsStudio({ initialVoice, active: visible }: { initialVoice: string; active: boolean }) {
  const voices = useAsync(friendly(() => voiceApi.profiles()), []);
  const [voice, setVoice] = useState(initialVoice);
  const [text, setText] = useState("");
  const [language, setLanguage] = useState("auto");
  const [speed, setSpeed] = useState(1);
  const [pitch, setPitch] = useState(0);
  const [temperature, setTemperature] = useState(0.9);
  const [seed, setSeed] = useState("");
  const [current, setCurrent] = useState<VoiceGeneration | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const ready = voices.data?.profiles.filter((p) => p.status === "ready") ?? [];
  const maxChars = voices.data?.limits.max_chars ?? 20000;

  // Stays mounted to keep the text, so the voice list is refreshed on each return.
  useEffect(() => {
    if (visible) voiceApi.profiles().then((r) => voices.setData(r)).catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible]);

  useEffect(() => { if (initialVoice) setVoice(initialVoice); }, [initialVoice]);

  // Also covers a selected voice that has since been deleted.
  useEffect(() => {
    if (!voices.data) return;
    if (!ready.some((p) => p.id === voice)) setVoice((ready.find((p) => p.is_default) ?? ready[0])?.id ?? "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [voices.data, voice]);

  const active = current && (current.status === "queued" || current.status === "running");
  useEffect(() => {
    if (!active || !current) return;
    const t = window.setInterval(() => voiceApi.generation(current.id).then(setCurrent).catch(() => undefined), 1000);
    return () => window.clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, current?.id]);

  async function generate() {
    setBusy(true);
    setError(null);
    try {
      setCurrent(await voiceApi.generate({
        profile_id: voice, text, language, speed, pitch_semitones: pitch, temperature, top_p: 1,
        seed: seed.trim() ? Number(seed) : null,
      }));
    } catch (e) {
      setError(voiceError(e));
    } finally {
      setBusy(false);
    }
  }

  async function cancel(id: string) {
    try {
      await voiceApi.cancelGeneration(id);
    } catch (e) {
      setError(voiceError(e));
    }
  }

  return (
    <AsyncBoundary state={voices} loadingLabel="Loading voices…">
      {() => (
        <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
          <div className="space-y-4">
            <div className="hud-panel hud-frame p-4">
              <ErrorLine error={error} />
              <Field label={`Text (${text.length} of ${maxChars})`} hint="Long text is split at sentences and paragraphs, then joined with natural pauses.">
                <textarea value={text} rows={10} maxLength={maxChars} onChange={(e) => setText(e.target.value)} className={inputCls} />
              </Field>
              <button onClick={generate} disabled={busy || !!active || !voice || !text.trim()} className={`${primaryBtnCls} mt-3`} style={primaryStyle}>
                <span className="flex items-center gap-2"><Play size={14} /> {active ? "Generating…" : "Generate"}</span>
              </button>
              {ready.length === 0 && <div className="kai-metadata mt-3">Create a voice first. It appears here once it's ready.</div>}
            </div>
            {current && <GenerationRow key={current.id} g={current} onCancel={cancel} />}
          </div>
          <div className="hud-panel hud-frame space-y-3 p-4">
            <SectionTitle>Settings</SectionTitle>
            <Field label="Voice"><VoiceSelect voices={voices.data?.profiles ?? []} value={voice} onChange={setVoice} /></Field>
            <Field label="Language"><LanguageSelect value={language} onChange={setLanguage} /></Field>
            <Slider label="Speed" value={speed} min={0.5} max={2} step={0.05} onChange={setSpeed} unit="×" hint="Applied after synthesis. The model has no speed control of its own." />
            <Slider label="Pitch" value={pitch} min={-12} max={12} step={0.5} onChange={setPitch} unit=" st" hint="Applied after synthesis. Large shifts reduce quality." />
            <Slider label="Expressiveness" value={temperature} min={0.1} max={1.5} step={0.05} onChange={setTemperature} hint="Sampling temperature. Lower is steadier, higher is more varied. This model has no emotion presets." />
            <Field label="Seed" hint="Optional. The same seed and settings repeat a result.">
              <input value={seed} inputMode="numeric" onChange={(e) => setSeed(e.target.value.replace(/\D/g, ""))} className={inputCls} />
            </Field>
          </div>
        </div>
      )}
    </AsyncBoundary>
  );
}
