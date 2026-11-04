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
  /** "reported spouse" for a spouse named on a web page */
  relation?: string;
  /** id of the web fact the node comes from */
  fact_id?: string | null;
}

export interface Relations {
  kin: Kin;
  associates: Edge[];
  weak_associates: Edge[];
  nodes: RelationNode[];
}

/** Person card (backend enrich/lookup.py _person_view); fields may be missing. */
export interface PersonRef {
  nid: string;
  name: string;
  sex?: string | null;
  date_of_birth?: string | null;
  marital_status?: string | null;
  district?: string | null;
  sector?: string | null;
  cell?: string | null;
  village?: string | null;
  phones?: string[];
  father_names?: string | null;
  mother_names?: string | null;
  [k: string]: unknown;
}

/** One web finding from the web agent (page, face, search hit or attribute). */
export interface WebFinding {
  type: string;
  url?: string;
  title?: string | null;
  value?: string;
  sources?: string[];
  face_id?: string;
}

export interface InvestigateResult {
  person: PersonRef | null;
  /** first 5 candidates; candidate_count is the true total */
  people: PersonRef[];
  candidate_count?: number;
  /** a name lookup matched several people */
  ambiguous?: boolean;
  relations: Relations | null;
  web_findings: WebFinding[];
  spouse_candidates: string[];
  name_collision_warning?: boolean;
  analysis: string | null;
  /** number of unsupported sentences the grounding check removed */
  analysis_dropped_count?: number;
  omitted_facts?: number;
  facts: Fact[];
  notes: string[];
  agents_run: string[];
}

export interface OneHopResult {
  person: PersonRef;
  ambiguous?: boolean;
  candidate_count?: number;
  relations: Relations | null;
  facts: Fact[];
  notes: string[];
  agents_run: string[];
}

export interface WebOnlyResult {
  person: null;
  web_only: true;
  name: string;
  findings: WebFinding[];
  spouse_candidates: string[];
  name_collision_warning?: boolean;
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

/** A citation group: "[F3]", "[F3, F4]" or "[F3; F4]" ("[F3][F4]" is two groups). */
export const CITATION_RE = /\[(F\d+(?:\s*[,;]\s*F\d+)*)\]/;

/** Turn "[F3]", "[F3, F4]" and "[F3][F4]" markers into one cite part per id. */
export function splitCitations(text: string): { type: "text" | "cite"; value: string }[] {
  const out: { type: "text" | "cite"; value: string }[] = [];
  const re = new RegExp(CITATION_RE.source, "g");
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push({ type: "text", value: text.slice(last, m.index) });
    for (const id of m[1].match(/F\d+/g) ?? []) out.push({ type: "cite", value: id });
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push({ type: "text", value: text.slice(last) });
  return out;
}

/** http(s) links only: anything else (javascript:, data:) is rendered as text. */
export const isHttpUrl = (s: string | null | undefined): s is string => !!s && /^https?:\/\//i.test(s);

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

/**
 * Neutralise images in model text so it cannot make the browser load a remote URL.
 * Nothing is removed, so nothing can be reassembled and citations such as
 * "[F1]: born 1980" stay intact: a "!" before "[" gets a space ("! [a](u)" parses
 * as the text "!" plus a link, never an image) and "<img" is escaped. react-markdown
 * without rehype-raw never renders HTML; the escape is belt and braces. Single linear passes.
 */
export function stripMarkdownImages(text: string): string {
  return text
    .replace(/!(?=[\s​-‍⁠﻿]*\[)/g, "! ")
    .replace(/<(?=\s*img)/gi, "&lt;");
}
