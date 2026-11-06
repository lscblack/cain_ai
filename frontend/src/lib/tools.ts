import { api } from "@/lib/api";
import type { Finding } from "@/lib/chat";

export interface ToolParam {
  name: string;
  kind: string;
  required: boolean;
  default: any;
  help: string;
}
export interface ToolOperation {
  key: string;
  title: string;
  description: string;
  posture: string;
  requires_authorization: boolean;
  needs_root: boolean;
  params: ToolParam[];
}
export interface ToolInfo {
  name: string;
  purpose: string;
  package: string;
  source: string;
  apt_available: boolean | null;
  categories: string[];
  installed: boolean;
  path: string | null;
  version: string | null;
  operations: ToolOperation[];
}
export interface Inventory {
  tools: ToolInfo[];
  counts: { total: number; installed: number; missing: number };
  verified_at: string;
}
export interface Execution {
  id: string;
  tool: string;
  operation: string;
  args: string[];
  target: string | null;
  posture: string | null;
  status: string;
  exit_code: number | null;
  duration_ms: number | null;
  stdout: string;
  stderr: string;
  error: string | null;
  created_at: string | null;
}
export interface Target {
  id: string;
  target: string;
  scope: string;
  note: string;
  active: boolean;
  created_at?: string | null;
}
export interface InstallReq {
  id: string;
  package: string;
  capability: string | null;
  source: string;
  reason: string;
  needs_root: boolean;
  status: string;
  installed_version: string | null;
  log: string;
  created_at: string | null;
  decided_at: string | null;
}

export const toolsApi = {
  inventory: () => api.get<Inventory>("/tools/inventory"),
  execute: (operation: string, params: Record<string, any>, conversation_id?: string) =>
    api.post<any>("/tools/execute", { operation, params, conversation_id }),
  executions: () => api.get<Execution[]>("/tools/executions"),
  findings: () => api.get<Finding[]>("/tools/findings"),
  targets: () => api.get<Target[]>("/tools/targets"),
  addTarget: (target: string, scope: string, note: string) =>
    api.post<Target>("/tools/targets", { target, scope, note }),
  removeTarget: (id: string) => api.del<void>(`/tools/targets/${id}`),
  installPlan: (body: { package?: string; capability?: string }) =>
    api.post<any>("/tools/install/plan", body),
  installRequests: () => api.get<InstallReq[]>("/tools/install/requests"),
  requestInstall: (body: { package?: string; capability?: string; reason: string }) =>
    api.post<{ request: InstallReq; plan: any }>("/tools/install/requests", body),
  approveInstall: (id: string) => api.post<any>(`/tools/install/requests/${id}/approve`),
  rejectInstall: (id: string) => api.post<InstallReq>(`/tools/install/requests/${id}/reject`),
  installNow: (body: { capability?: string; package?: string; reinstall?: boolean }) =>
    api.post<InstallNowResult>("/tools/install/now", body),
  installBatch: (capabilities: string[], reinstall = false) =>
    api.post<InstallBatchResult>("/tools/install/batch", { capabilities, reinstall }),
  sweep: (body: Record<string, string>) => api.post<SweepResult>("/tools/sweep", body),
  docs: () => api.get<ToolDoc[]>("/tools/docs"),
  getDoc: (id: string) => api.get<ToolDoc>(`/tools/docs/${id}`),
  addDoc: (body: ToolDocIn) => api.post<ToolDoc>("/tools/docs", body),
  deleteDoc: (id: string) => api.del<void>(`/tools/docs/${id}`),
  capabilities: () => api.get<Capabilities>("/tools/capabilities"),
  setCapabilities: (body: Partial<Capabilities>) => api.put<Capabilities>("/tools/capabilities", body),
  skills: () => api.get<Skill[]>("/tools/skills"),
  getSkill: (id: string) => api.get<Skill>(`/tools/skills/${id}`),
  addSkill: (body: SkillIn) => api.post<Skill>("/tools/skills", body),
  updateSkill: (id: string, body: Partial<SkillIn>) => api.patch<Skill>(`/tools/skills/${id}`, body),
  deleteSkill: (id: string) => api.del<void>(`/tools/skills/${id}`),
  customCapabilities: () => api.get<CustomCapability[]>("/tools/custom"),
  addCapability: (body: CapabilityIn) => api.post<CustomCapability>("/tools/custom", body),
  updateCapability: (id: string, body: CapabilityIn) => api.put<CustomCapability>(`/tools/custom/${id}`, body),
  deleteCapability: (id: string) => api.del<void>(`/tools/custom/${id}`),
};

export interface CapabilityOpIn {
  key: string;
  title?: string;
  description?: string;
  posture?: string;
  argv_template?: string;
  target_kind?: string | null;
  requires_authorization?: boolean;
  timeout?: number | null;
}
export interface CapabilityIn {
  name: string;
  title?: string;
  purpose?: string;
  category?: string;
  binary?: string;
  source?: string;
  package?: string;
  categories?: string[];
  operations: CapabilityOpIn[];
  enabled?: boolean;
}
export interface CustomCapability {
  id: string;
  name: string;
  title: string;
  category: string;
  enabled: boolean;
  entry: any;
  operations: { key: string; title: string; desc: string; posture: string; auth: boolean }[];
  source?: string;
  binary?: string;
  created_at: string | null;
}
export const TARGET_KINDS = [
  "", "domain", "host", "ip", "url", "username", "email", "phone", "onion", "term", "hash", "port_spec",
] as const;
export const TOOL_SOURCES = ["apt", "kali", "pip", "go", "github", "gem", "builtin"] as const;

export interface Skill {
  id: string;
  name: string;
  description: string;
  enabled: boolean;
  char_count: number;
  content_text?: string;
  created_at: string | null;
}
export interface SkillIn {
  name: string;
  description?: string;
  content: string;
  enabled?: boolean;
}

export interface Capabilities {
  tools_enabled: boolean;
  shell_enabled: boolean;
  shell_auto_run: boolean;
  shell_sudo: boolean;
}

export interface ToolDoc {
  id: string;
  tool_name: string | null;
  title: string;
  source_type: "url" | "file" | "text";
  source_ref: string | null;
  char_count: number;
  content_text?: string;
  created_at: string | null;
}
export interface ToolDocIn {
  source_type: "url" | "file" | "text";
  url?: string;
  content?: string;
  source_ref?: string;
  tool_name?: string;
  title?: string;
}

export interface SweepResult {
  ran: number;
  skipped: number;
  results: {
    identifier: string;
    kind: string;
    operation: string;
    tool: string | null;
    status: string;
    ok: boolean;
    execution_id?: string;
    summary: string;
  }[];
  note: string;
}

export interface InstallNowResult {
  request: InstallReq | null;
  outcome: { ok: boolean; status: string; error?: string | null; sudo_needs_password?: boolean };
  verify: { installed: boolean; version: string | null; path: string | null };
}
export interface InstallBatchResult {
  installed: { tool: string; package: string; version: string | null }[];
  failed: { tool: string; package: string }[];
  skipped: { tool: string; reason: string }[];
  outcome: { ok: boolean; status: string; error?: string | null; sudo_needs_password?: boolean } | null;
}
