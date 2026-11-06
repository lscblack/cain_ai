import { Trash2, X } from "lucide-react";

import type { VoiceGeneration } from "@/lib/voice";
import { AuthAudio, btnCls, DownloadAudio, formatDate, formatDuration, StatusTag } from "@/components/voice/shared";

export function GenerationRow({ g, onCancel, onDelete }: {
  g: VoiceGeneration; onCancel: (id: string) => void; onDelete?: (id: string) => void;
}) {
  const active = g.status === "queued" || g.status === "running";
  const short = g.id.slice(0, 8);
  return (
    <div className="hud-panel hud-frame p-3">
      <div className="mb-1 flex items-center justify-between gap-2">
        <span className="text-sm font-semibold">{g.profile_name ?? "Voice"}</span>
        <StatusTag status={g.status} />
      </div>
      <p className="mb-2 line-clamp-2 text-sm text-muted">{g.text}</p>
      {active && (
        <div className="mb-2">
          <div className="hud-bar"><span style={{ width: `${Math.max(3, g.progress * 100)}%` }} /></div>
          <button className={`${btnCls} mt-2`} onClick={() => onCancel(g.id)}><X size={12} /> Cancel</button>
        </div>
      )}
      {g.status === "failed" && <div className="mb-2 text-sm" style={{ color: "var(--kai-accent)" }}>{g.error}</div>}
      {g.status === "completed" && (
        <div className="space-y-2">
          <AuthAudio path={`/voice/generations/${g.id}/audio?format=wav`} />
          <div className="flex flex-wrap items-center gap-2">
            <DownloadAudio path={`/voice/generations/${g.id}/audio?format=wav`} filename={`kai-speech-${short}.wav`} label="WAV" />
            <DownloadAudio path={`/voice/generations/${g.id}/audio?format=mp3`} filename={`kai-speech-${short}.mp3`} label="MP3" />
          </div>
        </div>
      )}
      <div className="mt-2 flex items-center justify-between gap-2">
        <div className="kai-metadata">
          {formatDate(g.created_at)}
          {g.status === "completed" && ` · ${formatDuration(g.duration_s)} audio · took ${g.inference_s.toFixed(1)}s on ${g.device || "unknown"}`}
        </div>
        {onDelete && !active && <button className={btnCls} onClick={() => onDelete(g.id)}><Trash2 size={12} /> Delete</button>}
      </div>
    </div>
  );
}
