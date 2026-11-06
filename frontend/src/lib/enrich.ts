import { api, API_BASE, getToken } from "@/lib/api";

export interface EndpointCfg {
  id: string;
  slug: string;
  title: string;
  category: string;
  description: string;
  kind: string;
  method: string;
  url_template: string;
  query_template: Record<string, any>;
  headers: Record<string, any>;
  body_template: Record<string, any>;
  auth_type: string;
  auth_config: Record<string, any>;
  result_path: string;
  image_keys: string[];
  enabled: boolean;
  rate_limit_per_min: number;
  sample_response: string;
  created_at: string | null;
}

export type EndpointIn = Omit<EndpointCfg, "id" | "created_at">;

export interface ScrapeJob {
  id: string;
  kind: string;
  status: string;
  total: number;
  processed: number;
  stats: Record<string, number>;
  last_message: string;
  rate_limit_per_min: number;
  running: boolean;
  started_at: string | null;
  finished_at: string | null;
  created_at: string | null;
  log?: { t: string; level: string; msg: string }[];
  parsed_rows?: number;
  parse_errors?: string[];
}

export interface PersonRow {
  id: string;
  nid: string;
  name: string;
  surnames?: string | null;
  forenames?: string | null;
  sex?: string | null;
  date_of_birth?: string | null;
  father_names?: string | null;
  mother_names?: string | null;
  nationality?: string | null;
  civil_status?: string | null;
  province?: string | null;
  district?: string | null;
  sector?: string | null;
  cell?: string | null;
  village?: string | null;
  place_of_birth?: string | null;
  document_number?: string | null;
  date_of_issue?: string | null;
  date_of_expiry?: string | null;
  photo_face_id?: string | null;
  crop_url?: string | null;
  last_scraped_at?: string | null;
  phones?: { msisdn: string; mno: string | null; service_period: string | null }[];
  parcels?: { upi: string; is_current: boolean; start_date: string | null; end_date: string | null; source: string }[];
  upi_count?: number;
  raw?: Record<string, any>;
}

export interface ParcelRow {
  id: string;
  upi: string;
  province?: string | null;
  district?: string | null;
  sector?: string | null;
  cell?: string | null;
  village?: string | null;
  land_use?: string | null;
  size?: number | null;
  current_owner_nid?: string | null;
  last_scraped_at?: string | null;
  ownership_history?: {
    owner_nid: string | null;
    is_current: boolean;
    start_date: string | null;
    end_date: string | null;
    transaction_type: string | null;
    sale_price: number | null;
    source: string;
  }[];
}

export interface EnrichStats {
  persons: number;
  parcels: number;
  phones: number;
  ownership_records: number;
  jobs: number;
}

export const enrichApi = {
  endpoints: () => api.get<{ endpoints: EndpointCfg[]; kinds: string[] }>("/enrich/endpoints"),
  createEndpoint: (body: EndpointIn) => api.post<EndpointCfg>("/enrich/endpoints", body),
  updateEndpoint: (id: string, body: EndpointIn) => api.put<EndpointCfg>(`/enrich/endpoints/${id}`, body),
  deleteEndpoint: (id: string) => api.del<void>(`/enrich/endpoints/${id}`),
  testEndpoint: (id: string, params: Record<string, any>) =>
    api.post<any>(`/enrich/endpoints/${id}/test`, { params }),
  reseed: () => api.post<{ created: number }>("/enrich/endpoints/seed"),

  jobs: () => api.get<ScrapeJob[]>("/enrich/jobs"),
  job: (id: string) => api.get<ScrapeJob>(`/enrich/jobs/${id}`),
  startPhone: (phones: string[], rate_limit_per_min: number) =>
    api.post<ScrapeJob>("/enrich/jobs/phone", { phones, rate_limit_per_min }),
  startNid: (nids: string[], rate_limit_per_min: number) =>
    api.post<ScrapeJob>("/enrich/jobs/nid", { nids, rate_limit_per_min }),
  controlJob: (id: string, action: "pause" | "resume" | "cancel") =>
    api.post<any>(`/enrich/jobs/${id}/${action}`),
  startCsv: (file: File, rate: number, expand: boolean) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("rate_limit_per_min", String(rate));
    fd.append("expand_owner_parcels", String(expand));
    return api.postForm<ScrapeJob>("/enrich/jobs/csv", fd);
  },

  stats: () => api.get<EnrichStats>("/enrich/stats"),
  persons: (q = "", limit = 50) =>
    api.get<PersonRow[]>(`/enrich/persons?q=${encodeURIComponent(q)}&limit=${limit}`),
  person: (nid: string) => api.get<PersonRow>(`/enrich/persons/${encodeURIComponent(nid)}`),
  parcels: (q = "", limit = 50) =>
    api.get<ParcelRow[]>(`/enrich/parcels?q=${encodeURIComponent(q)}&limit=${limit}`),
  parcel: (upi: string) => api.get<ParcelRow>(`/enrich/parcels/${encodeURIComponent(upi)}`),
  personByFace: (faceId: string) => api.get<PersonRow>(`/enrich/person/by-face/${faceId}`),
};

// Absolute URL for an <img> (crops are served by the backend, auth via query is
// not needed because crop endpoints are same-origin through the proxy).
export function cropSrc(url: string | null | undefined): string | undefined {
  if (!url) return undefined;
  return `${API_BASE}${url}`;
}

export { getToken };

// ── people search + family ────────────────────────────────────────────────── //
export interface RelativeBase {
  nid: string;
  name: string;
  sex?: string | null;
  date_of_birth?: string | null;
  place_of_birth?: string | null;
  nationality?: string | null;
  marital_status?: string | null;
  document_number?: string | null;
  father_names?: string | null;
  mother_names?: string | null;
  province?: string | null;
  district?: string | null;
  sector?: string | null;
  cell?: string | null;
  village?: string | null;
  photo_url?: string | null;
}

export interface Relative extends RelativeBase {
  relation: "father" | "mother" | "sibling" | "child" | "extended";
  label: string;
  confidence: number;
  reasons: string[];
  /** Present on a parent found in the DB: their phones and everyone recorded as their child. */
  phones?: string[];
  children?: (RelativeBase & { recorded_as: "father" | "mother"; is_subject: boolean })[];
}

/** A web-scraped face linked to a person, with everything the index holds for it. */
export interface WebFace {
  face_id: string;
  crop_url: string | null;
  source_url?: string | null;
  page_title?: string | null;
  match_pct: number;
  caption?: string | null;
  context?: string | null;
  names?: string[];
  phones?: string[];
  emails?: string[];
  usernames?: string[];
  titles?: string[];
  orgs?: string[];
  locations?: string[];
  age?: number | null;
  sex?: string | null;
}

export interface PersonCardData {
  nid: string;
  name: string;
  sex?: string | null;
  date_of_birth?: string | null;
  father_names?: string | null;
  mother_names?: string | null;
  district?: string | null;
  sector?: string | null;
  cell?: string | null;
  village?: string | null;
  phones: string[];
  upi_count?: number;
  upis?: string[];
  nationality?: string | null;
  place_of_birth?: string | null;
  marital_status?: string | null;
  province?: string | null;
  document_number?: string | null;
  photo_url?: string | null;
  web_photos?: WebFace[];
  match_pct: number | null;
  matched_by: string[];
  relatives?: {
    parents: Relative[]; siblings: Relative[]; children: Relative[];
    /** grandparents, uncles/aunts, cousins, nephews/nieces… found by walking the family graph */
    extended?: (Relative & { path: string[]; via: string[] })[];
  } | null;
}

export interface WebMatch {
  face_id: string;
  match_pct: number;
  crop_url: string | null;
  source_url?: string | null;
  page_title?: string | null;
  names: string[];
  phones: string[];
  locations: string[];
}

export interface FaceMatch extends WebMatch {
  kind: "nid" | "web";
  caption?: string | null;
  context?: string | null;
  emails: string[];
  usernames: string[];
  orgs: string[];
  titles: string[];
  age?: number | null;
  sex?: string | null;
  linked_nid: string | null;
  linked_by: string | null;
}

export interface PeopleSearchResult {
  ok?: boolean;
  min_match_pct?: number;
  faces_detected?: number;
  people: PersonCardData[];
  web_matches?: WebMatch[];
  /** every face-index match ≥ min_match_pct, best first (NID photos and web faces) */
  face_matches?: FaceMatch[];
  notes?: string[];
  disclaimer?: string;
}

export const peopleApi = {
  /** Any mix of image / nid / phone / name. Face matches below 49% are dropped server-side. */
  search: (q: { file?: File; nid?: string; phone?: string; name?: string; min_pct?: number }) => {
    const fd = new FormData();
    if (q.file) fd.append("file", q.file);
    if (q.nid) fd.append("nid", q.nid);
    if (q.phone) fd.append("phone", q.phone);
    if (q.name) fd.append("name", q.name);
    if (q.min_pct != null) fd.append("min_pct", String(q.min_pct));
    return api.postForm<PeopleSearchResult>("/enrich/people/search", fd);
  },
  family: (nid: string) =>
    api.get<{ nodes: any[]; edges: any[]; relatives: PersonCardData["relatives"] }>(`/enrich/family/${nid}`),
};

// ── everything crawled around one web face ───────────────────────────────── //
export interface WebFaceDetail {
  face: {
    face_id: string; crop_url: string | null; source_url: string | null; image_url: string | null;
    image_size: [number, number] | null; detected_at: string | null; quality: number; det_score: number;
    page_title?: string | null; caption?: string | null; alt?: string | null; context?: string | null;
    age?: number | null; sex?: string | null;
    names: string[]; phones: string[]; emails: string[]; usernames: string[];
    titles: string[]; orgs: string[]; locations: string[];
  };
  page: {
    url: string; title: string | null; description: string | null;
    emails: string[]; phones: string[]; usernames: string[]; meta: Record<string, any>;
    http_status: number | null; images_found: number; faces_found: number;
    last_crawled_at: string | null; last_changed_at: string | null;
  } | null;
  source: { name: string; domain: string; base_url: string; category: string | null; last_crawled_at: string | null } | null;
  same_page_faces: { face_id: string; crop_url: string | null; names: string[] }[];
  site_pages: { url: string; title: string | null; faces_found: number; emails: string[]; phones: string[] }[];
  appearances: {
    face_id: string; crop_url: string | null; match_pct: number; kind: "nid" | "web";
    source_url: string | null; page_title: string | null; names: string[]; nid?: string | null;
  }[];
}

export const webFaceApi = {
  detail: (faceId: string) => api.get<WebFaceDetail>(`/enrich/web-face/${faceId}`),
};
