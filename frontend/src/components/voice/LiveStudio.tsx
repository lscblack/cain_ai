import { useEffect, useState, useSyncExternalStore } from "react";
import { Mic, Square } from "lucide-react";

import { AsyncBoundary, useAsync } from "@/components/Async";
import { liveConversion } from "@/lib/liveConversion";
import { friendly, voiceApi, voiceError, type VirtualMicStatus } from "@/lib/voice";
import {
  btnCls, ErrorLine, Field, Meter, primaryBtnCls, primaryStyle, SectionTitle, selectCls, StatusTag, VoiceSelect,
} from "@/components/voice/shared";

function Stat({ label, value, warn }: { label: string; value: string; warn?: boolean }) {
  return (
    <div className="border border-line bg-panel-2 p-2">
      <div className="kai-metadata">{label}</div>
      <div className="hud-mono text-sm" style={warn ? { color: "var(--kai-warn)" } : undefined}>{value}</div>
    </div>
  );
}

const ms = (v: number | null) => (v === null ? "—" : `${Math.round(v)} ms`);
const ACTIVE = new Set(["starting", "live", "reconnecting"]);

export function LiveStudio() {
  const live = useSyncExternalStore(liveConversion.subscribe, liveConversion.getSnapshot);
  const voices = useAsync(friendly(() => voiceApi.profiles()), []);
  const [voice, setVoice] = useState(live.profileId ?? "");
  const [inputs, setInputs] = useState<MediaDeviceInfo[]>([]);
  const [outputs, setOutputs] = useState<MediaDeviceInfo[]>([]);
  const [vmic, setVmic] = useState<VirtualMicStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [, rerender] = useState(0);
  const s = liveConversion.settings;
  const active = ACTIVE.has(live.state);

  function update(patch: Partial<typeof s>) {
    liveConversion.updateSettings(patch);
    rerender((n) => n + 1);
  }

  useEffect(() => {
    if (!voices.data) return;
    const ready = voices.data.profiles.filter((p) => p.status === "ready");
    if (!ready.some((p) => p.id === voice)) setVoice((ready.find((p) => p.is_default) ?? ready[0])?.id ?? "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [voices.data]);

  async function refreshDevices() {
    try {
      const list = await navigator.mediaDevices.enumerateDevices();
      setInputs(list.filter((d) => d.kind === "audioinput"));
      setOutputs(list.filter((d) => d.kind === "audiooutput"));
    } catch { /* no device access yet: the system defaults still work */ }
  }

  useEffect(() => {
    void refreshDevices();
    navigator.mediaDevices?.addEventListener?.("devicechange", refreshDevices);
    return () => navigator.mediaDevices?.removeEventListener?.("devicechange", refreshDevices);
  }, []);
  useEffect(() => { if (live.state === "live") void refreshDevices(); }, [live.state]);
  useEffect(() => { voiceApi.conversionStatus().then((r) => setVmic(r.virtual_mic)).catch((e) => setError(voiceError(e))); }, []);

  async function toggleVirtualMic(enabled: boolean) {
    setError(null);
    try {
      setVmic(await voiceApi.setVirtualMic(enabled));
      update({ virtualMic: enabled });
    } catch (e) {
      setError(voiceError(e));
    }
  }

  function changeVoice(id: string) {
    setVoice(id);
    if (active) liveConversion.setTarget(id);
  }

  const shownError = error ?? (live.state === "error" && live.error ? voiceError({ detail: live.error }) : null);

  return (
    <AsyncBoundary state={voices} loadingLabel="Loading voices…">
      {(data) => (
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="space-y-4">
            <div className="hud-panel hud-frame p-4" style={active ? { borderColor: "var(--kai-accent)" } : undefined}>
              <div className="mb-3 flex items-center justify-between">
                <SectionTitle inline>Conversion</SectionTitle>
                {active ? (
                  <span className="hud-mono flex items-center gap-2 text-xs" style={{ color: "var(--kai-accent)" }}>
                    <span className="h-2 w-2 animate-pulse rounded-full" style={{ background: "var(--kai-accent)" }} />
                    {live.state === "live"
                      ? live.delayed ? "DELAYED: converting your microphone, not in real time"
                        : live.nearLive ? `CONVERTING: about ${live.latencyMs === null ? "a few" : (live.latencyMs / 1000).toFixed(1)} s behind you`
                        : "LIVE: your microphone is being converted"
                      : live.stage || "Starting"}
                  </span>
                ) : <StatusTag status="stopped" />}
              </div>
              <ErrorLine error={shownError} />
              {live.nearLive && active && (
                <div className="mb-4 text-sm" style={{ color: "var(--kai-warn)" }}>
                  No working GPU, so your voice is converted in {(live.blockMs / 1000).toFixed(1)} s pieces. It's continuous, but too far behind for a natural conversation.
                </div>
              )}
              {live.notice && <div className="mb-4 text-sm" style={{ color: "var(--kai-warn)" }}>{live.notice}</div>}
              {live.micLost && <div className="mb-3 text-sm" style={{ color: "var(--kai-warn)" }}>{live.stage}</div>}
              {live.tooSlow && !active && (
                <div className="mb-4 border p-3 text-sm" style={{ borderColor: "var(--kai-warn)" }}>
                  <div className="mb-2" style={{ color: "var(--kai-warn)" }}>
                    Live conversion can't run on this hardware right now. {live.tooSlow.engine} took {Math.round(live.tooSlow.procMs)} ms
                    on the {live.tooSlow.device} to convert {Math.round(live.tooSlow.blockMs)} ms of speech, so it would fall further behind with every word.
                  </div>
                  <div className="kai-metadata mb-3">Model Management shows the hardware status. If the GPU failed to initialize, restart the computer and try again.</div>
                  <button className={btnCls} onClick={() => { setError(null); void liveConversion.start(voice, { delayed: true }); }}>
                    Convert with a delay instead (not live)
                  </button>
                </div>
              )}
              <div className="mb-4">
                <Field label="Target voice"><VoiceSelect voices={data.profiles} value={voice} onChange={changeVoice} /></Field>
              </div>
              {active ? (
                <button onClick={() => liveConversion.stop()} className={primaryBtnCls} style={{ borderColor: "var(--kai-accent)", color: "var(--kai-accent)" }}>
                  <span className="flex items-center gap-2"><Square size={14} /> Stop conversion</span>
                </button>
              ) : (
                <button onClick={() => { setError(null); void liveConversion.start(voice); }} disabled={!voice || live.state === "stopping"} className={primaryBtnCls} style={primaryStyle}>
                  <span className="flex items-center gap-2"><Mic size={14} /> Start conversion</span>
                </button>
              )}
              <div className="mt-4 space-y-3">
                <Meter value={live.inputLevel} label={`Microphone${live.speaking ? " · speech detected" : ""}`} />
                <Meter value={live.outputLevel} label="Converted output" />
              </div>
            </div>

            <div className="hud-panel hud-frame p-4">
              <SectionTitle>Measured performance</SectionTitle>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                <Stat label="Latency (median)" value={ms(live.latencyMs)} />
                <Stat label="Latency (p95)" value={ms(live.latencyP95Ms)} />
                <Stat label="Processing per block" value={ms(live.procMs)} warn={live.procMs !== null && live.procMs > live.blockMs} />
                <Stat label="Block size" value={live.blockMs ? `${Math.round(live.blockMs)} ms` : "—"} />
                <Stat label="Output buffer" value={`${Math.round(live.bufferMs)} ms`} />
                {live.delayed && <Stat label="Behind the microphone" value={`${(live.backlogMs / 1000).toFixed(1)} s`} warn />}
                <Stat label="Speed vs. real time" value={live.realtimeFactor === null ? "—" : `${live.realtimeFactor.toFixed(2)}×`} warn={live.realtimeFactor !== null && live.realtimeFactor < 1} />
                <Stat label="Blocks sent / received" value={`${live.blocksSent} / ${live.blocksReceived}`} />
                <Stat label="Dropped (too slow)" value={String(live.blocksDroppedByServer)} warn={live.blocksDroppedByServer > 0} />
                <Stat label="Output gaps" value={String(live.underruns)} warn={live.underruns > 0} />
              </div>
              <div className="kai-metadata mt-3">
                {live.engine ? `${live.engine} on ${live.device}` : "Engine details appear once conversion starts."}
                {live.blocksDroppedByServer > 0 && !live.delayed && " · This hardware can't keep up, so some speech is being dropped."}
                {live.underruns > 0 && live.blocksDroppedByServer === 0 && " · Output gaps mean audio arrived late. Closing other heavy programs helps."}
              </div>
            </div>
          </div>

          <div className="space-y-4">
            <div className="hud-panel hud-frame space-y-3 p-4">
              <SectionTitle>Devices and monitoring</SectionTitle>
              <Field label="Microphone">
                <select value={s.inputDeviceId} onChange={(e) => update({ inputDeviceId: e.target.value })} className={selectCls}>
                  <option value="">System default</option>
                  {inputs.map((d) => <option key={d.deviceId} value={d.deviceId}>{d.label || "Microphone"}</option>)}
                </select>
              </Field>
              <Field label="Output device" hint={live.outputSinkSupported ? undefined : "This browser can't choose an output device, so it uses the system default."}>
                <select value={s.outputDeviceId} disabled={!live.outputSinkSupported} onChange={(e) => update({ outputDeviceId: e.target.value })} className={selectCls}>
                  <option value="">System default</option>
                  {outputs.map((d) => <option key={d.deviceId} value={d.deviceId}>{d.label || "Speaker"}</option>)}
                </select>
              </Field>
              <Field label={`Microphone volume: ${Math.round(s.inputGain * 100)}%`}>
                <input type="range" className="w-full" min={0} max={2} step={0.05} value={s.inputGain} onChange={(e) => update({ inputGain: Number(e.target.value) })} />
              </Field>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={s.monitorConverted} onChange={(e) => update({ monitorConverted: e.target.checked })} />
                Hear the converted voice
              </label>
              <Field label={`Converted volume: ${Math.round(s.outputVolume * 100)}%`}>
                <input type="range" className="w-full" disabled={!s.monitorConverted} min={0} max={1.5} step={0.05} value={s.outputVolume} onChange={(e) => update({ outputVolume: Number(e.target.value) })} />
              </Field>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={s.monitorOriginal} onChange={(e) => update({ monitorOriginal: e.target.checked })} />
                Hear my original voice
              </label>
              <Field label={`Original volume: ${Math.round(s.monitorOriginalVolume * 100)}%`}>
                <input type="range" className="w-full" disabled={!s.monitorOriginal} min={0} max={1} step={0.05} value={s.monitorOriginalVolume} onChange={(e) => update({ monitorOriginalVolume: Number(e.target.value) })} />
              </Field>
              <div className="kai-metadata" style={{ color: "var(--kai-warn)" }}>Use headphones while monitoring, or your speakers will feed back into the microphone.</div>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={s.noiseSuppression} onChange={(e) => update({ noiseSuppression: e.target.checked })} />
                Noise suppression
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={s.echoCancellation} onChange={(e) => update({ echoCancellation: e.target.checked })} />
                Echo cancellation
              </label>
            </div>

            <div className="hud-panel hud-frame p-4">
              <SectionTitle>Virtual microphone</SectionTitle>
              <p className="mb-3 text-sm text-muted">Sends the converted voice to a system microphone that apps on this computer can select.</p>
              {vmic && !vmic.supported ? (
                <div className="text-sm" style={{ color: "var(--kai-warn)" }}>Not available: missing {vmic.missing.join(", ")}.</div>
              ) : (
                <>
                  <label className="flex items-center gap-2 text-sm">
                    <input type="checkbox" checked={!!vmic?.enabled} onChange={(e) => toggleVirtualMic(e.target.checked)} />
                    Enable "{vmic?.source_description ?? "KAI Voice Microphone"}"
                  </label>
                  {vmic?.enabled && (
                    <ol className="kai-metadata mt-3 list-decimal space-y-1 pl-4">
                      <li>In Discord, Zoom, Meet or another app, open its audio settings.</li>
                      <li>Choose "{vmic.source_description}" as the microphone.</li>
                      <li>Start conversion here and speak. The app's input meter should move.</li>
                      <li>Tell people on the call that your voice is being converted.</li>
                    </ol>
                  )}
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </AsyncBoundary>
  );
}
