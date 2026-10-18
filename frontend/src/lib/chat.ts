import { api, getToken } from "@/lib/api";

const BASE = import.meta.env.VITE_API_URL ?? "/api";

// ───────────────────────── types ──────────────────────────────────── //
export interface ModelStatus {
  endpoint: string;
  model: string;
  reachable: boolean;
  model_installed: boolean;
  models_available: string[];
  error: string | null;
  ready: boolean;
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
  deleteConversation: (id: string) => api.del<void>(`/chat/conversations/${id}`),
};

// ───────────────────────── SSE streaming ──────────────────────────── //
export async function streamMessage(
  conversationId: string,
  content: string,
  useTools: boolean,
  onEvent: (e: SseEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const resp = await fetch(`${BASE}/chat/conversations/${conversationId}/messages`, {
    method: "POST",
    headers,
    body: JSON.stringify({ content, use_tools: useTools }),
    signal,
  });
  if (!resp.ok || !resp.body) {
    const text = await resp.text().catch(() => "");
    throw new Error(text || `request failed (${resp.status})`);
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let evName = "message";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";
    for (const frame of frames) {
      evName = "message";
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
