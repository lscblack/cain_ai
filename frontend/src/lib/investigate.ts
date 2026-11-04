import { API_BASE, getToken } from "@/lib/api";

export interface Fact {
  id: string;
  claim: string;
  value: string;
  source: "db" | "web" | "inference";
  source_ref: string;
  retrieved_at: string;
  confidence: number;
}

export interface SharedFact {
  what: string;
  value: string;
  source: string;
  source_ref: string;
  count: number;
  total: number;
}

export interface Edge {
  person_a: string;
  person_b: string | null;
  name_b: string;
  relation: string;
  shared: SharedFact[];
  confidence: number;
  confirmed: boolean;
}

/** A relative from family.relatives_out / extended_out, or a partner entry. */
export interface KinEntry {
  nid: string | null;
  name: string;
  label?: string;
  relation?: string;
  confidence?: number;
  reasons?: string[];
  date_of_birth?: string | null;
  photo_url?: string | null;
  ambiguous?: boolean;
  in_system?: boolean;
  children?: unknown[];
}

export interface Kin {
  partners: KinEntry[];
  parents: KinEntry[];
  children: KinEntry[];
  siblings: KinEntry[];
  extended: KinEntry[];
}

export interface RelationNode {
  nid: string | null;
  name: string;
  in_system: boolean;
  source_ref: string | null;
  ambiguous?: boolean;
}

export interface Relations {
  kin: Kin;
  associates: Edge[];
  weak_associates: Edge[];
  nodes: RelationNode[];
}

export interface PersonRef {
  nid: string;
  name: string;
  [k: string]: unknown;
}

export interface InvestigateResult {
  person: PersonRef | null;
  people: PersonRef[];
  relations: Relations | null;
  web_findings: unknown[];
  spouse_candidates: string[];
  analysis: string | null;
  dropped?: string[];
  facts: Fact[];
  notes: string[];
  agents_run: string[];
}

export interface OneHopResult {
  person: PersonRef;
  relations: Relations | null;
  facts: Fact[];
  notes: string[];
  agents_run: string[];
}

export interface WebOnlyResult {
  person: null;
  web_only: true;
  name: string;
  findings: unknown[];
  spouse_candidates: string[];
  facts: Fact[];
  notes: string[];
  lookup_hint: string;
}

export interface InvestigateBody {
  nid?: string;
  phone?: string;
  name?: string;
  web: boolean;
  analyse: boolean;
}

export type InvestigateEvent =
  | { event: "agent_start"; data: { agent: string } }
  | { event: "agent_done"; data: { agent: string } }
  | { event: "agent_error"; data: { agent: string } }
  | { event: "result"; data: InvestigateResult }
  | { event: "error"; data: { detail: string } };

/** Split an SSE buffer into complete events; `rest` is the unfinished tail. */
export function parseSseFrames(buffer: string): { events: { event: string; data: any }[]; rest: string } {
  const parts = buffer.replace(/\r\n/g, "\n").split("\n\n");
  const rest = parts.pop() ?? "";
  const events: { event: string; data: any }[] = [];
  for (const frame of parts) {
    let event = "message";
    const data: string[] = [];
    for (const line of frame.split("\n")) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) data.push(line.slice(5).trim());
    }
    if (!data.length) continue;
    try {
      events.push({ event, data: JSON.parse(data.join("\n")) });
    } catch {
      /* malformed frame: ignore */
    }
  }
  return { events, rest };
}

/** Turn "[F3]" markers in text into cite parts. */
export function splitCitations(text: string): { type: "text" | "cite"; value: string }[] {
  const out: { type: "text" | "cite"; value: string }[] = [];
  const re = /\[(F\d+)\]/g;
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push({ type: "text", value: text.slice(last, m.index) });
    out.push({ type: "cite", value: m[1] });
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push({ type: "text", value: text.slice(last) });
  return out;
}

export function visibleEdges(edges: Edge[], weak: Edge[], showWeak: boolean): Edge[] {
  return showWeak ? [...edges, ...weak] : edges;
}

async function errorText(resp: Response): Promise<string> {
  const text = await resp.text().catch(() => "");
  try {
    const d = JSON.parse(text)?.detail;
    if (typeof d === "string") return d;
  } catch {
    /* not JSON */
  }
  return text || `request failed (${resp.status})`;
}

export async function investigateStream(
  body: InvestigateBody,
  onEvent: (e: InvestigateEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const token = getToken();
  const resp = await fetch(`${API_BASE}/enrich/people/investigate`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: JSON.stringify(body),
    signal,
  });
  if (!resp.ok || !resp.body) throw new Error(await errorText(resp));
  const reader = resp.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    const { events, rest } = parseSseFrames(buf);
    buf = rest;
    for (const ev of events) onEvent({ event: ev.event, data: ev.data } as InvestigateEvent);
  }
  // flush a final frame that lacked its trailing blank line
  const { events } = parseSseFrames(buf + "\n\n");
  for (const ev of events) onEvent({ event: ev.event, data: ev.data } as InvestigateEvent);
}

export async function personOneHop(nid: string, signal?: AbortSignal): Promise<OneHopResult | WebOnlyResult> {
  const token = getToken();
  const resp = await fetch(`${API_BASE}/enrich/people/${encodeURIComponent(nid)}/investigate`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    signal,
  });
  if (!resp.ok) throw new Error(await errorText(resp));
  return (await resp.json()) as OneHopResult | WebOnlyResult;
}

/** Remove markdown/HTML images so model text cannot make the browser load a remote URL. */
export function stripMarkdownImages(text: string): string {
  return text
    .replace(/!\[[^\]]*\]\([^)]*\)/g, "") // ![alt](url)
    .replace(/!\[[^\]]*\]\[[^\]]*\]/g, "") // ![alt][ref]
    .replace(/!\[[^\]]*\](?!\()/g, "") // ![ref]
    .replace(/^[ \t]*\[[^\]]+\]:[ \t]*\S+.*$/gm, "") // [ref]: url
    .replace(/<img\b[^>]*>?/gi, "");
}
