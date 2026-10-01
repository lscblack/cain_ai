export interface Operator {
  id: string;
  email: string;
  created_at: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

export interface ReadinessResponse {
  ready: boolean;
  db: "up" | "down";
  redis: "up" | "down";
}

export class ApiError extends Error {
  status: number;
  detail: string;
  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
    this.detail = detail;
  }
}

export type EntityType =
  | "face" | "phone" | "email" | "username" | "domain" | "url" | "image"
  | "organization" | "location" | "document" | "vehicle" | "aircraft" | "vessel";

export interface Investigation {
  id: string;
  code: string;
  name: string;
  description: string | null;
  status: "open" | "archived";
  created_at: string;
  updated_at: string;
}

export interface InvestigationDetail extends Investigation {
  entity_count: number;
  evidence_count: number;
  relationship_count: number;
}

export interface EntityNode {
  id: string;
  investigation_id: string;
  type: EntityType;
  value: string;
  label: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface EvidenceItem {
  id: string;
  investigation_id: string;
  entity_id: string | null;
  type: EntityType;
  source_url: string;
  collected_at: string;
  first_seen: string | null;
  last_seen: string | null;
  hash: string | null;
  confidence: number | null;
  band: string | null;
  raw_metadata: Record<string, unknown>;
  processed_metadata: Record<string, unknown>;
  created_at: string;
}

export interface RelationshipEdge {
  id: string;
  investigation_id: string;
  source_entity_id: string;
  target_entity_id: string;
  rel_type: string;
  source_url: string;
  observed_at: string;
  confidence: number | null;
  evidence_excerpt: string | null;
  created_at: string;
}

export interface CaseGraph {
  nodes: EntityNode[];
  edges: RelationshipEdge[];
}

export interface SearchResponse {
  query: string;
  detected_type: "url" | "email" | "phone" | "domain" | "username" | "unknown";
  normalized: string;
  entity_matches: EntityNode[];
  evidence_matches: EvidenceItem[];
}

export interface PhoneAnalysis {
  input: string;
  parsed: boolean;
  valid: boolean;
  possible: boolean;
  e164: string | null;
  international: string | null;
  national: string | null;
  country_code: number | null;
  region: string | null;
  location: string | null;
  carrier: string | null;
  number_type: string;
  variants: string[];
  error: string | null;
}

export interface PhoneIntelligence {
  analysis: PhoneAnalysis;
  local_entity_matches: EntityNode[];
  local_evidence_matches: EvidenceItem[];
  note: string;
}

export interface EmailAnalysis {
  input: string;
  valid_format: boolean;
  local: string | null;
  domain: string | null;
  gravatar_url: string | null;
  derived_usernames: string[];
  mx_records: string[] | null;
  has_mx: boolean | null;
  spf: string | null;
  dmarc: string | null;
  dns_checked: boolean;
  notes: string[];
}

export interface EmailIntelligence {
  analysis: EmailAnalysis;
  local_entity_matches: EntityNode[];
  local_evidence_matches: EvidenceItem[];
  note: string;
}

export interface UsernameHit {
  platform: string;
  name: string;
  username: string;
  url: string;
  status: "found" | "not_found" | "unknown" | "error";
  http_status: number | null;
  checked_at: string;
}

export interface UsernameIntelligence {
  username: string;
  results: UsernameHit[];
  found_count: number;
  local_entity_matches: EntityNode[];
  note: string;
}
