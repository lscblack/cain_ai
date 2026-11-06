import { useEffect, useState } from "react";
import { Pencil, RefreshCw, Star, Trash2 } from "lucide-react";

import { AsyncBoundary, useAsync } from "@/components/Async";
import { friendly, LANGUAGES, voiceApi, voiceError, type VoiceProfile } from "@/lib/voice";
import {
  AuthAudio, btnCls, ConsentFields, consentForm, consentOk, ErrorLine, Field, formatDate, formatDuration,
  inputCls, LanguageSelect, primaryBtnCls, primaryStyle, StatusTag,
} from "@/components/voice/shared";

export function Library({ onCreate, onUse }: { onCreate: () => void; onUse: (id: string) => void }) {
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);
  const state = useAsync(friendly(() => voiceApi.profiles(query).then((r) => r.profiles)), [query]);
  const { retry } = state;

  useEffect(() => {
    const t = window.setTimeout(() => setQuery(q.trim()), 250);
    return () => window.clearTimeout(t);
  }, [q]);

  const processing = state.data?.some((p) => p.status === "processing");
  useEffect(() => {
    if (!processing) return;
    const t = window.setInterval(() => voiceApi.profiles(query).then((r) => state.setData(r.profiles)).catch(() => undefined), 2000);
    return () => window.clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [processing, query]);

  return (
    <div>
      <div className="mb-4 flex gap-2">
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search voices" className={`${inputCls} flex-1`} />
        <button onClick={onCreate} className={primaryBtnCls} style={primaryStyle}>New voice</button>
      </div>
      <ErrorLine error={error} />
      <AsyncBoundary state={state} loadingLabel="Loading voices…">
        {(profiles) => profiles.length === 0 ? (
          <div className="kai-metadata py-10 text-center">{query ? "No voices match that search." : "No voices yet. Create one to get started."}</div>
        ) : (
          <div className="grid gap-3 md:grid-cols-2">
            {profiles.map((p) => <VoiceCard key={p.id} profile={p} onChanged={retry} onError={setError} onUse={onUse} />)}
          </div>
        )}
      </AsyncBoundary>
    </div>
  );
}

function VoiceCard({ profile: p, onChanged, onError, onUse }: {
  profile: VoiceProfile; onChanged: () => void; onError: (e: string | null) => void; onUse: (id: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [replacing, setReplacing] = useState(false);
  const [draft, setDraft] = useState({ name: p.name, description: p.description, language: p.language, transcript: p.transcript });

  async function act(fn: () => Promise<unknown>): Promise<boolean> {
    onError(null);
    try {
      await fn();
      onChanged();
      return true;
    } catch (e) {
      onError(voiceError(e));
      return false;
    }
  }

  // Analysis fills in fields after creation, so the form starts from the current values.
  function openEditor() {
    setDraft({ name: p.name, description: p.description, language: p.language, transcript: p.transcript });
    setEditing((v) => !v);
  }

  const languageName = LANGUAGES.find(([id]) => id === p.language)?.[1] ?? p.language;

  return (
    <div className="hud-panel hud-frame p-4">
      <div className="mb-2 flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-semibold">
            {p.is_default && <Star size={13} style={{ color: "var(--kai-hud)" }} />}
            <span className="truncate">{p.name}</span>
          </div>
          {p.description && <div className="kai-metadata mt-0.5">{p.description}</div>}
        </div>
        <StatusTag status={p.status} />
      </div>

      {p.status === "processing" && <div className="kai-metadata mb-2" style={{ color: "var(--kai-hud)" }}>{p.status_detail}…</div>}
      {p.status === "failed" && <div className="mb-2 text-sm" style={{ color: "var(--kai-accent)" }}>{p.status_detail}</div>}

      <div className="kai-metadata mb-3">
        {languageName} · {formatDuration(p.duration_s)} reference{p.model_id ? ` · ${p.model_id}` : ""} · created {formatDate(p.created_at)}
        <br />
        Consent: {p.consent_basis === "own_voice" ? "own voice" : `permission from ${p.consent_subject}`} · {formatDate(p.consent_at)}
      </div>

      <AuthAudio key={p.updated_at} path={`/voice/profiles/${p.id}/reference/audio`} />

      <div className="mt-3 flex flex-wrap gap-2">
        {p.status === "ready" && <button className={btnCls} onClick={() => onUse(p.id)}>Generate speech</button>}
        <button className={btnCls} onClick={openEditor}><Pencil size={12} /> Edit</button>
        <button className={btnCls} onClick={() => setReplacing((v) => !v)}>Replace recording</button>
        {!p.is_default && <button className={btnCls} onClick={() => act(() => voiceApi.patchProfile(p.id, { is_default: true }))}><Star size={12} /> Set default</button>}
        {(p.status === "failed" || p.status === "ready") && (
          <button className={btnCls} onClick={() => act(() => voiceApi.reclone(p.id))}>
            <RefreshCw size={12} /> {p.status === "failed" ? "Retry" : "Re-analyze"}
          </button>
        )}
        <button className={btnCls} onClick={() => {
          if (confirm(`Delete '${p.name}'? This removes its recording, voice data and all speech generated with it.`)) act(() => voiceApi.deleteProfile(p.id));
        }}><Trash2 size={12} /> Delete</button>
      </div>

      {editing && (
        <div className="mt-3 space-y-2 border-t border-line pt-3">
          <Field label="Name"><input value={draft.name} maxLength={120} onChange={(e) => setDraft({ ...draft, name: e.target.value })} className={inputCls} /></Field>
          <Field label="Description"><input value={draft.description} maxLength={2000} onChange={(e) => setDraft({ ...draft, description: e.target.value })} className={inputCls} /></Field>
          <Field label="Language"><LanguageSelect value={draft.language} onChange={(language) => setDraft({ ...draft, language })} /></Field>
          <Field label="Transcript" hint="Saving a new transcript only takes effect after you retry the analysis.">
            <textarea value={draft.transcript} rows={3} maxLength={5000} onChange={(e) => setDraft({ ...draft, transcript: e.target.value })} className={inputCls} />
          </Field>
          <div className="flex gap-2">
            <button className={btnCls} onClick={() => act(() => voiceApi.patchProfile(p.id, draft)).then((ok) => { if (ok) setEditing(false); })}>Save</button>
            {draft.transcript !== p.transcript && (
              <button className={btnCls} onClick={() => act(async () => { await voiceApi.patchProfile(p.id, draft); await voiceApi.reclone(p.id); }).then((ok) => { if (ok) setEditing(false); })}>Save and re-analyze</button>
            )}
          </div>
        </div>
      )}
      {replacing && <ReplaceRecording id={p.id} onDone={() => { setReplacing(false); onChanged(); }} onError={onError} />}
    </div>
  );
}

function ReplaceRecording({ id, onDone, onError }: { id: string; onDone: () => void; onError: (e: string | null) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [transcript, setTranscript] = useState("");
  const [consent, setConsent] = useState({ confirmed: false, basis: "own_voice", subject: "" });
  const [busy, setBusy] = useState(false);

  async function submit() {
    if (!file) return;
    setBusy(true);
    onError(null);
    try {
      const form = new FormData();
      form.set("file", file);
      form.set("transcript", transcript);
      consentForm(form, consent);
      await voiceApi.replaceReference(id, form);
      onDone();
    } catch (e) {
      onError(voiceError(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-3 space-y-2 border-t border-line pt-3">
      <Field label="New recording"><input type="file" accept="audio/*" onChange={(e) => setFile(e.target.files?.[0] ?? null)} className={inputCls} /></Field>
      <Field label="Transcript of the new recording"><textarea value={transcript} rows={2} maxLength={5000} onChange={(e) => setTranscript(e.target.value)} className={inputCls} /></Field>
      <ConsentFields value={consent} onChange={setConsent} />
      <button className={btnCls} disabled={busy || !file || !consentOk(consent)} onClick={submit}>{busy ? "Uploading…" : "Replace and re-analyze"}</button>
    </div>
  );
}
