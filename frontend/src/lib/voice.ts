import { beginRequest, endRequest } from "@/lib/activity";
import { api, API_BASE, getToken } from "@/lib/api";
import { ApiError } from "@/types";

export interface VoiceProfile {
  id: string;
  name: string;
  description: string;
  language: string;
  transcript: string;
  status: "draft" | "processing" | "ready" | "failed";
  status_detail: string;
  is_default: boolean;
  model_id: string;
  model_version: string;
  consent_confirmed: boolean;
  consent_basis: string;
  consent_subject: string;
  consent_at: string | null;
  duration_s: number;
  meta: Record<string, any>;
  created_at: string | null;
  updated_at: string | null;
}

export interface VoiceGeneration {
  id: string;
  profile_id: string;
  profile_name: string | null;
  text: string;
  language: string;
  params: { speed?: number; pitch_semitones?: number; temperature?: number; top_p?: number; seed?: number | null };
  status: "queued" | "running" | "completed" | "failed" | "canceled";
  progress: number;
  error: string;
  engine_id: string;
  engine_version: string;
  device: string;
  duration_s: number;
  inference_s: number;
  created_at: string | null;
  finished_at: string | null;
}

export interface VoiceModel {
  id: string;
  name: string;
  kind: "tts" | "vc" | "asr" | "vad";
  license: string;
  description: string;
  optional: boolean;
  repo_url: string;
  revision: string;
  download_gb: number;
  min_ram_gb: number;
  min_vram_gb: number;
  status: string;
  installed: boolean;
  loaded: boolean;
  device: string | null;
  size_bytes: number;
  location: string;
  env_path: string;
  env_ready: boolean;
  install: { state: string; step: string; progress: number; error: string; log: string[] } | null;
  health: Record<string, any>;
  compatibility: { ok: boolean; notes: string[] };
  realtime: Record<string, any> | null;
}

export interface VoiceHardware {
  cpu: { model: string; threads: number };
  ram: { total_gb: number; available_gb: number };
  disk_free_gb: number;
  gpu: {
    pci_present: boolean;
    pci_name: string;
    driver_loaded: boolean;
    driver_version: string;
    smi_ok: boolean;
    smi_message: string;
    name: string;
    vram_total_mb: number;
    vram_free_mb: number;
    torch: Record<string, any> | null;
  };
  selected_device: string;
  summary: string;
}

export interface VirtualMicStatus {
  supported: boolean;
  missing: string[];
  enabled: boolean;
  source_name: string;
  source_description: string;
  sink_name: string;
}

export const LANGUAGES = [
  ["auto", "Auto-detect"], ["english", "English"], ["chinese", "Chinese"], ["french", "French"],
  ["german", "German"], ["italian", "Italian"], ["japanese", "Japanese"], ["korean", "Korean"],
  ["portuguese", "Portuguese"], ["russian", "Russian"], ["spanish", "Spanish"],
] as const;

export const voiceApi = {
  profiles: (q = "") => api.get<{ profiles: VoiceProfile[]; limits: { max_chars: number; max_upload_mb: number } }>(
    `/voice/profiles${q ? `?q=${encodeURIComponent(q)}` : ""}`),
  profile: (id: string) => api.get<VoiceProfile>(`/voice/profiles/${id}`),
  createProfile: (form: FormData) => api.postForm<VoiceProfile>("/voice/profiles", form),
  patchProfile: (id: string, body: Partial<Pick<VoiceProfile, "name" | "description" | "language" | "transcript" | "is_default">>) =>
    api.patch<VoiceProfile>(`/voice/profiles/${id}`, body),
  deleteProfile: (id: string) => api.del<{ deleted: boolean; generations_deleted: number }>(`/voice/profiles/${id}`),
  reclone: (id: string, modelId?: string) => api.post<VoiceProfile>(`/voice/profiles/${id}/clone`, { model_id: modelId ?? null }),
  replaceReference: async (id: string, form: FormData) => {
    const token = getToken();
    let res: Response;
    beginRequest();
    try {
      res = await fetch(`${API_BASE}/voice/profiles/${id}/reference`, {
        method: "PUT", headers: token ? { Authorization: `Bearer ${token}` } : {}, body: form,
      });
    } catch {
      throw new ApiError(0, "network_error");
    } finally {
      endRequest();
    }
    const data = await res.json().catch(() => null);
    if (!res.ok) throw new ApiError(res.status, typeof data?.detail === "string" ? data.detail : "request_failed");
    return data as VoiceProfile;
  },
  generate: (body: {
    profile_id: string; text: string; language: string; speed: number; pitch_semitones: number;
    temperature: number; top_p: number; seed: number | null;
  }) => api.post<VoiceGeneration>("/voice/tts/generate", body),
  generations: (limit = 50, offset = 0) => api.get<{ generations: VoiceGeneration[] }>(`/voice/generations?limit=${limit}&offset=${offset}`),
  generation: (id: string) => api.get<VoiceGeneration>(`/voice/generations/${id}`),
  cancelGeneration: (id: string) => api.post<{ status: string }>(`/voice/generations/${id}/cancel`),
  deleteGeneration: (id: string) => api.del<{ deleted: boolean }>(`/voice/generations/${id}`),
  models: () => api.get<{ models: VoiceModel[] }>("/voice/models"),
  hardware: (probe = false) => api.get<VoiceHardware>(`/voice/hardware${probe ? "?probe=true" : ""}`),
  modelAction: (id: string, action: "install" | "load" | "unload" | "health") =>
    api.post<Record<string, any>>(`/voice/models/${id}`, { action }),
  conversionStatus: () => api.get<{ active: boolean; virtual_mic: VirtualMicStatus; engine: Record<string, any> | null }>("/voice/conversion/status"),
  setVirtualMic: (enabled: boolean) => api.put<VirtualMicStatus>("/voice/conversion/virtual-mic", { enabled }),
};

/** Audio routes need the bearer token, so they cannot be a plain src or href. */
export async function fetchVoiceAudio(path: string): Promise<Blob> {
  const token = getToken();
  let res: Response;
  beginRequest();
  try {
    res = await fetch(`${API_BASE}${path}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  } catch {
    throw new ApiError(0, "network_error");
  } finally {
    endRequest();
  }
  if (res.status === 403) throw new ApiError(403, "voice_local_only");
  if (!res.ok) throw new ApiError(res.status, "audio_not_available");
  return res.blob();
}

const MESSAGES: Record<string, string> = {
  voice_local_only: "Voice features only work from this machine (open KAI on localhost). Remote access is off by default.",
  consent_required: "Confirm you have the right to use this voice.",
  consent_subject_required: "Name the person who gave permission.",
  voice_name_taken: "You already have a voice with that name.",
  unsupported_audio_format: "That file isn't a supported audio format (WAV, MP3, FLAC, OGG, WebM, M4A).",
  audio_file_too_large: "That file is over the upload limit.",
  empty_audio_file: "That file is empty.",
  voice_not_ready: "That voice is not ready yet.",
  voice_not_found: "That voice no longer exists.",
  text_too_long: "That text is over the length limit.",
  live_conversion_active: "Stop live conversion first. Both can't share the hardware.",
  voice_in_use_by_live_conversion: "This voice is in use by live conversion. Stop it first.",
  rate_limited: "Too many requests. Wait a minute and try again.",
  network_error: "Can't reach the KAI backend.",
  not_authenticated: "Your session has expired. Sign in again.",
  model_not_installed: "That model isn't installed yet. Install it under Model Management.",
  environment_missing: "That model's environment isn't installed. Install it under Model Management.",
  install_in_progress: "Another installation is already running.",
  no_realtime_engine: "No live conversion engine is installed. Install one under Model Management.",
  tts_in_progress: "A voice is being analyzed or speech is being generated. Wait for it to finish, then start conversion.",
  audio_not_available: "That audio is no longer available.",
  no_audio_stream: "That file has no audio track.",
  audio_decode_failed: "That audio file couldn't be decoded.",
  session_already_active: "Live conversion is already running in another tab.",
  pipewire_tools_missing: "PipeWire tools are missing on this machine.",
  virtual_mic_failed: "PipeWire couldn't create the virtual microphone.",
};

export function voiceError(e: any): string {
  const code = String(e?.detail ?? e?.message ?? e?.code ?? e);
  // Worker failures arrive as "code: detail".
  return MESSAGES[code] ?? MESSAGES[code.split(":")[0]] ?? code;
}

/** For useAsync loaders, which display the error message as written. */
export function friendly<T>(load: () => Promise<T>): () => Promise<T> {
  return () => load().catch((e) => { throw new Error(voiceError(e)); });
}
