import { useCallback, useEffect, useRef, useState } from "react";

// Minimal typings for the Web Speech API (not in TS DOM lib). Kept local so the
// feature degrades to "unsupported" on browsers without it.
type SR = any;
function getSR(): (new () => SR) | null {
  const w = window as any;
  return w.SpeechRecognition || w.webkitSpeechRecognition || null;
}

export interface VoiceHandlers {
  /** A completed utterance (already wake-word-stripped when applicable). */
  onFinal: (text: string) => void;
  /** Live partial text, for echoing into the composer. */
  onInterim?: (text: string) => void;
}

/** Continuous speech recognition with optional wake-word gating.
 * Returns controls; listening auto-restarts until explicitly stopped. */
export function useVoice({ onFinal, onInterim }: VoiceHandlers) {
  const [supported] = useState(() => getSR() !== null);
  const [listening, setListening] = useState(false);
  const recRef = useRef<SR | null>(null);
  const wantRef = useRef(false);          // should we keep (re)starting?
  const wakeRef = useRef(false);          // require the wake word?
  const finalRef = useRef(onFinal);
  const interimRef = useRef(onInterim);
  finalRef.current = onFinal;
  interimRef.current = onInterim;

  const handleFinal = useCallback((raw: string) => {
    let text = raw.trim();
    if (!text) return;
    if (wakeRef.current) {
      // Only act when the wake word is present; strip everything up to it.
      const m = text.match(/\b(hey\s+)?(kai|k\.?a\.?i\.?)\b[\s,:-]*/i);
      if (!m) return;
      text = text.slice((m.index ?? 0) + m[0].length).trim();
      if (!text) return;
    }
    finalRef.current(text);
  }, []);

  const start = useCallback((opts?: { wake?: boolean }) => {
    const Ctor = getSR();
    if (!Ctor) return;
    wakeRef.current = !!opts?.wake;
    wantRef.current = true;
    if (recRef.current) return;   // already running
    const rec: SR = new Ctor();
    rec.continuous = true;
    rec.interimResults = true;
    rec.lang = "en-US";
    rec.onresult = (e: any) => {
      let interim = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const res = e.results[i];
        if (res.isFinal) handleFinal(res[0].transcript);
        else interim += res[0].transcript;
      }
      if (interim && interimRef.current) interimRef.current(interim);
    };
    rec.onend = () => {
      recRef.current = null;
      if (wantRef.current) {
        // Auto-restart (the engine stops periodically) unless we were told to stop.
        try { start({ wake: wakeRef.current }); } catch { setListening(false); }
      } else {
        setListening(false);
      }
    };
    rec.onerror = (e: any) => {
      // "no-speech"/"aborted" are benign; a permission error should stop us.
      if (e?.error === "not-allowed" || e?.error === "service-not-allowed") {
        wantRef.current = false;
      }
    };
    recRef.current = rec;
    try { rec.start(); setListening(true); } catch { /* already started */ }
  }, [handleFinal]);

  const stop = useCallback(() => {
    wantRef.current = false;
    const rec = recRef.current;
    recRef.current = null;
    try { rec?.stop(); } catch { /* */ }
    setListening(false);
  }, []);

  useEffect(() => () => { wantRef.current = false; try { recRef.current?.stop(); } catch { /* */ } }, []);

  return { supported, listening, start, stop };
}

/** Speak text aloud (markdown/code stripped). Best-effort; no-op if unavailable. */
export function speak(text: string) {
  const synth = window.speechSynthesis;
  if (!synth || !text) return;
  const clean = text
    .replace(/```[\s\S]*?```/g, " code block ")
    .replace(/`[^`]*`/g, " ")
    .replace(/[#*_>\-]/g, " ")
    .replace(/\[(.*?)\]\(.*?\)/g, "$1")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 1200);
  if (!clean) return;
  try {
    synth.cancel();
    const u = new SpeechSynthesisUtterance(clean);
    u.rate = 1.03;
    synth.speak(u);
  } catch { /* */ }
}

export function stopSpeaking() {
  try { window.speechSynthesis?.cancel(); } catch { /* */ }
}
