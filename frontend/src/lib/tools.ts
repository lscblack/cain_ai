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
  sweep: (body: Record<string, string>) => api.post<SweepResult>("/tools/sweep", body),
};

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
