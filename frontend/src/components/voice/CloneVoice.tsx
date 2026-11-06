import { useEffect, useRef, useState } from "react";
import { Mic, Square, Upload } from "lucide-react";

import { voiceApi, voiceError } from "@/lib/voice";
import {
  ConsentFields, consentForm, consentOk, ErrorLine, Field, formatDuration, inputCls, LanguageSelect,
  Meter, primaryBtnCls, primaryStyle, SectionTitle, selectCls,
} from "@/components/voice/shared";

const READING_PROMPT =
  "The morning light came slowly over the hills, and I walked down to the river to watch the water move. " +
  "Some days are quiet and simple, and that is exactly what makes them worth remembering.";

export function CloneVoice({ onCreated }: { onCreated: () => void }) {
  const [source, setSource] = useState<"upload" | "record">("record");
  const [file, setFile] = useState<Blob | null>(null);
  const [fileName, setFileName] = useState("");
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [language, setLanguage] = useState("auto");
  const [transcript, setTranscript] = useState("");
  const [consent, setConsent] = useState({ confirmed: false, basis: "own_voice", subject: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [mics, setMics] = useState<MediaDeviceInfo[]>([]);
  const [micId, setMicId] = useState("");
  const [recording, setRecording] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [level, setLevel] = useState(0);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const cleanupRef = useRef<(() => void) | null>(null);
  const opening = useRef(false);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      if (recorderRef.current?.state === "recording") {
        recorderRef.current.onstop = null;
        recorderRef.current.stop();
      }
      cleanupRef.current?.();
    };
  }, []);
  useEffect(() => () => { if (previewUrl) URL.revokeObjectURL(previewUrl); }, [previewUrl]);
  useEffect(() => {
    navigator.mediaDevices?.enumerateDevices?.().then((d) => setMics(d.filter((x) => x.kind === "audioinput"))).catch(() => undefined);
  }, [recording]);

  function pickRecording(blob: Blob | null, label: string) {
    setFile(blob);
    setFileName(label);
    setPreviewUrl(blob ? URL.createObjectURL(blob) : null);
  }

  async function startRecording() {
    setError(null);
    if (opening.current || recording) return;
    if (!navigator.mediaDevices?.getUserMedia) {
      setError("This browser can't record here. Open KAI on localhost or over HTTPS.");
      return;
    }
    opening.current = true;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { deviceId: micId ? { exact: micId } : undefined, channelCount: 1, noiseSuppression: true, echoCancellation: true, autoGainControl: true },
      });
      if (!mounted.current) {  // left the page during the permission prompt
        stream.getTracks().forEach((t) => t.stop());
        return;
      }
      const ctx = new AudioContext();
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 1024;
      ctx.createMediaStreamSource(stream).connect(analyser);
      const data = new Float32Array(analyser.fftSize);
      const started = performance.now();
      const timer = window.setInterval(() => {
        analyser.getFloatTimeDomainData(data);
        setLevel(data.reduce((m, v) => Math.max(m, Math.abs(v)), 0));
        setElapsed((performance.now() - started) / 1000);
      }, 80);
      const chunks: Blob[] = [];
      const recorder = new MediaRecorder(stream);
      recorder.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
      const cleanup = () => {
        window.clearInterval(timer);
        stream.getTracks().forEach((t) => t.stop());
        void ctx.close();
        cleanupRef.current = null;
      };
      recorder.onstop = () => {
        cleanup();
        pickRecording(new Blob(chunks, { type: recorder.mimeType }), "Microphone recording");
        setRecording(false);
        setLevel(0);
      };
      cleanupRef.current = cleanup;
      recorderRef.current = recorder;
      recorder.start();
      setElapsed(0);
      setRecording(true);
    } catch (e: any) {
      setError(e?.name === "NotAllowedError" ? "Microphone permission was denied." : `Couldn't open the microphone: ${e?.message ?? e}`);
    } finally {
      opening.current = false;
    }
  }

  async function submit() {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const form = new FormData();
      const ext = file.type.includes("webm") ? "webm" : file.type.includes("ogg") ? "ogg" : file.type.includes("mp4") ? "m4a" : "";
      form.set("file", file, file instanceof File ? file.name : `recording.${ext || "webm"}`);
      form.set("name", name.trim());
      form.set("description", description);
      form.set("language", language);
      form.set("transcript", transcript);
      consentForm(form, consent);
      await voiceApi.createProfile(form);
      // This form stays mounted between tabs: the next voice starts clean, with new consent.
      pickRecording(null, "");
      setName("");
      setDescription("");
      setTranscript("");
      setConsent({ confirmed: false, basis: "own_voice", subject: "" });
      onCreated();
    } catch (e) {
      setError(voiceError(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <div className="hud-panel hud-frame p-4">
        <SectionTitle>1. Voice recording</SectionTitle>
        <div className="mb-4 flex gap-1 border-b border-line">
          {(["record", "upload"] as const).map((s) => (
            <button key={s} onClick={() => setSource(s)} disabled={recording}
              className={`flex items-center gap-1 border-b-2 px-3 py-2 hud-mono text-xs ${source === s ? "" : "border-transparent text-muted"}`}
              style={source === s ? { color: "var(--kai-hud)", borderColor: "var(--kai-hud)" } : undefined}>
              {s === "record" ? <Mic size={13} /> : <Upload size={13} />} {s === "record" ? "Record" : "Upload"}
            </button>
          ))}
        </div>

        {source === "record" ? (
          <div className="space-y-3">
            <Field label="Microphone">
              <select value={micId} onChange={(e) => setMicId(e.target.value)} disabled={recording} className={selectCls}>
                <option value="">System default</option>
                {mics.map((m) => <option key={m.deviceId} value={m.deviceId}>{m.label || "Microphone"}</option>)}
              </select>
            </Field>
            <div>
              <div className="kai-metadata mb-1">Read this aloud, in your normal speaking voice</div>
              <p className="border border-line bg-panel-2 p-3 text-sm">{READING_PROMPT}</p>
              <button onClick={() => setTranscript(READING_PROMPT)} className="kai-metadata mt-1 underline">Use this as the transcript</button>
            </div>
            <Meter value={level} label={recording ? `Recording ${formatDuration(elapsed)}` : "Input level"} />
            {recording ? (
              <button onClick={() => recorderRef.current?.stop()} className={primaryBtnCls} style={{ borderColor: "var(--kai-accent)", color: "var(--kai-accent)" }}>
                <span className="flex items-center gap-2"><Square size={14} /> Stop</span>
              </button>
            ) : (
              <button onClick={startRecording} className={primaryBtnCls} style={primaryStyle}>
                <span className="flex items-center gap-2"><Mic size={14} /> Start recording</span>
              </button>
            )}
          </div>
        ) : (
          <Field label="Audio file" hint="WAV, MP3, FLAC, OGG, WebM or M4A. Use 5 to 30 seconds of clear speech from one person.">
            <input type="file" accept="audio/*,.wav,.mp3,.flac,.ogg,.webm,.m4a"
              onChange={(e) => { const f = e.target.files?.[0] ?? null; pickRecording(f, f?.name ?? ""); }}
              className={inputCls} />
          </Field>
        )}

        {previewUrl && (
          <div className="mt-4">
            <div className="kai-metadata mb-1">{fileName}</div>
            <audio src={previewUrl} controls className="h-9 w-full" />
          </div>
        )}
      </div>

      <div className="hud-panel hud-frame space-y-3 p-4">
        <SectionTitle>2. Voice details</SectionTitle>
        <ErrorLine error={error} />
        <Field label="Name">
          <input value={name} maxLength={120} onChange={(e) => setName(e.target.value)} className={inputCls} />
        </Field>
        <Field label="Description">
          <input value={description} maxLength={2000} onChange={(e) => setDescription(e.target.value)} className={inputCls} />
        </Field>
        <Field label="Language">
          <LanguageSelect value={language} onChange={setLanguage} />
        </Field>
        <Field label="Transcript of the recording" hint="An exact transcript gives the best match. Leave it empty and KAI transcribes the recording locally.">
          <textarea value={transcript} maxLength={5000} rows={3} onChange={(e) => setTranscript(e.target.value)} className={inputCls} />
        </Field>
        <ConsentFields value={consent} onChange={setConsent} />
        <button onClick={submit} disabled={busy || recording || !file || !name.trim() || !consentOk(consent)} className={primaryBtnCls} style={primaryStyle}>
          {busy ? "Uploading…" : "Create voice"}
        </button>
      </div>
    </div>
  );
}
