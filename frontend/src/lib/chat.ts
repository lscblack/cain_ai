import { api, getToken, API_BASE } from "@/lib/api";

const BASE = API_BASE;

// ───────────────────────── types ──────────────────────────────────── //
export interface ModelStatus {
  endpoint: string;
  model: string;
  reachable: boolean;
  model_installed: boolean;
  models_available: string[];
  models_detail?: { name: string; backend: "ollama" | "llamacpp" }[];
  error: string | null;
  ready: boolean;
  backend?: "ollama" | "llamacpp";
  accelerator?: string | null;
}

export interface Conversation {
  id: string;
  title: string;
  model: string;
  archived: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system" | "tool";
  content: string;
  tool_calls: any[] | null;
  tool_results: any[] | null;
  meta: any;
  created_at: string | null;
}

export interface Finding {
  id?: string;
  title: string;
  description?: string;
  severity: string;
  confidence: string;
  status: string;
  asset?: string | null;
  tool?: string | null;
  evidence?: string[];
  impact?: string;
  remediation?: string;
  validation?: string;
  limitations?: string;
  created_at?: string | null;
}

export interface SseEvent {
  event: string;
  data: any;
}

/** What `service.preview_operation` returns: the real command KAI is about to
 * run, so the operator sees it before it happens. */
export interface ToolPreview {
  ok: boolean;
  tool?: string;
  operation?: string;
  posture?: string;
  requires_authorization?: boolean;
  needs_authorization?: boolean;
  target?: string | null;
  preview?: string;         // the redacted command line (or "(builtin) …")
  params?: Record<string, any>;
  status?: string;          // present when ok=false, e.g. "blocked"
  reason?: string;
  message?: string;
  error?: string;
}

// ───────────────────────── REST ───────────────────────────────────── //
export const chatApi = {
  status: () => api.get<ModelStatus>("/chat/status"),
  models: () => api.get<{ models: string[]; configured: string; error?: string }>("/chat/models"),
  listConversations: () => api.get<Conversation[]>("/chat/conversations"),
  getConversation: (id: string) =>
    api.get<Conversation & { messages: ChatMessage[] }>(`/chat/conversations/${id}`),
  createConversation: (body: { title?: string; model?: string } = {}) =>
    api.post<Conversation>("/chat/conversations", body),
  renameConversation: (id: string, title: string) =>
    api.patch<Conversation>(`/chat/conversations/${id}`, { title }),
  setConversationModel: (id: string, model: string) =>
    api.patch<Conversation>(`/chat/conversations/${id}`, { model }),
  deleteConversation: (id: string) => api.del<void>(`/chat/conversations/${id}`),
  active: () => api.get<ActiveRun[]>("/chat/active"),
  cancel: (id: string) => api.post<{ cancelled: boolean }>(`/chat/conversations/${id}/cancel`),
  approve: (id: string, approved: boolean) =>
    api.post<{ ok: boolean; approved: boolean }>(`/chat/conversations/${id}/approve`, { approved }),
  assets: () => api.get<{ files: KaiAsset[] }>("/chat/files"),
  deleteAsset: (id: string) => api.del<void>(`/chat/files/${id}`),
  summarize: (id: string) => api.post<{ summary: string }>(`/chat/conversations/${id}/summary`),
  getProfile: () => api.get<OperatorProfile>("/chat/profile"),
  setProfile: (content: string) => api.put<OperatorProfile>("/chat/profile", { content }),
  learnProfile: (conversation_id: string) => api.post<OperatorProfile>("/chat/profile/learn", { conversation_id }),
};

export interface OperatorProfile {
  content_text: string;
  char_count: number;
  updated_at: string | null;
}

export interface KaiAsset {
  id: string;
  name: string;
  size: number;
  content_type: string;
  download_url: string;
  created_at: string | null;
}

// ───────────────────────── SSE streaming ──────────────────────────── //
export interface ActiveRun {
  conversation_id: string;
  activity: string;
  started_at: number;
  seconds: number;
}

function authHeaders(): Record<string, string> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  return headers;
}

async function readSse(resp: Response, onEvent: (e: SseEvent) => void): Promise<void> {
  if (!resp.body) return;
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";
    for (const frame of frames) {
      let evName = "message";
      let dataLine = "";
      for (const line of frame.split("\n")) {
        if (line.startsWith("event: ")) evName = line.slice(7).trim();
        else if (line.startsWith("data: ")) dataLine += line.slice(6);
      }
      if (dataLine) {
        try {
          onEvent({ event: evName, data: JSON.parse(dataLine) });
        } catch {
          /* ignore malformed frame */
        }
      }
    }
  }
}

/** Send a message. The turn runs on the server; this connection only follows it. */
export async function streamMessage(
  conversationId: string,
  content: string,
  useTools: boolean,
  onEvent: (e: SseEvent) => void,
  signal?: AbortSignal,
  autoApprove = false,
  think = false,
  mode: "auto" | "multi" = "auto",
): Promise<void> {
  const resp = await fetch(`${BASE}/chat/conversations/${conversationId}/messages`, {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify({ content, use_tools: useTools, auto_approve: autoApprove, think, mode }),
    signal,
  });
  if (!resp.ok || !resp.body) {
    const text = await resp.text().catch(() => "");
    throw new Error(text || `request failed (${resp.status})`);
  }
  await readSse(resp, onEvent);
}

/** Re-attach to a turn that is still running (replays it from the start). */
export async function attachStream(
  conversationId: string,
  onEvent: (e: SseEvent) => void,
  signal?: AbortSignal,
): Promise<boolean> {
  const resp = await fetch(`${BASE}/chat/conversations/${conversationId}/stream`, {
    headers: authHeaders(),
    signal,
  });
  if (resp.status === 204 || !resp.ok || !resp.body) return false;
  await readSse(resp, onEvent);
  return true;
}
