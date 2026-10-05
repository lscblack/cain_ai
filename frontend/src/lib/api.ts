import { ApiError } from "@/types";

const BASE = import.meta.env.VITE_API_URL ?? "/api";
const TOKEN_KEY = "kai.token";

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null): void {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable (private mode) — token stays in memory only */
  }
}

function formatDetail(data: any, fallback: string): string {
  const d = data?.detail;
  if (!d) return fallback || "request_failed";
  if (typeof d === "string") return d;
  if (Array.isArray(d)) {
    // FastAPI/Pydantic validation errors: [{loc, msg, ...}]
    return d
      .map((e: any) => {
        const field = Array.isArray(e?.loc) ? e.loc[e.loc.length - 1] : "";
        return field ? `${field}: ${e?.msg ?? "invalid"}` : (e?.msg ?? "invalid");
      })
      .join("; ");
  }
  if (typeof d === "object") return d.msg ?? JSON.stringify(d);
  return String(d);
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;

  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, "network_error");
  }

  const text = await res.text();
  const data = text ? JSON.parse(text) : null;

  if (!res.ok) {
    throw new ApiError(res.status, formatDetail(data, res.statusText));
  }
  return data as T;
}

async function postForm<T>(path: string, form: FormData): Promise<T> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, { method: "POST", headers, body: form });
  } catch {
    throw new ApiError(0, "network_error");
  }
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) {
    throw new ApiError(res.status, formatDetail(data, res.statusText));
  }
  return data as T;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body),
  patch: <T>(path: string, body?: unknown) => request<T>("PATCH", path, body),
  del: <T>(path: string) => request<T>("DELETE", path),
  postForm,
};
