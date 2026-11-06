import { api } from "@/lib/api";

export interface FaceAppearance {
  face_id: string;
  crop_url?: string | null;
  image_url?: string | null;
  source_url?: string | null;
  page_title?: string | null;
  caption?: string | null;
  context?: string | null;
  similarity_pct: number;
  band?: string;
}

export interface FacePerson {
  person_id: string;
  name?: string | null;
  names: string[];
  emails?: string[];
  phones?: string[];
  usernames?: string[];
  titles?: string[];
  orgs?: string[];
  locations?: string[];
  contexts?: string[];
  age?: number | null;
  sex?: string | null;
  similarity_pct: number;
  band?: string;
  crop_url?: string | null;
  appearance_count: number;
  appearances?: FaceAppearance[];
  description?: string | null;
  // Present when the match is a scraped national-ID record.
  kind?: string | null;
  nid?: string | null;
  nid_person_id?: string | null;
  bio?: {
    date_of_birth?: string | null;
    father_names?: string | null;
    mother_names?: string | null;
    place_of_birth?: string | null;
    nationality?: string | null;
    document_number?: string | null;
  } | null;
}

export interface FaceSearchResult {
  faces_detected: number;
  indexed_faces?: number;
  people?: FacePerson[];
  matches?: any[];
  faces?: any[];
  query_face?: any;
  note?: string;
}

export interface DiscoverMatch {
  title?: string | null;
  source_url?: string | null;
  image_url?: string | null;
  similarity?: number;
}

export interface DiscoverResult {
  available: boolean;
  hint?: string;
  candidates_seen?: number;
  matches?: DiscoverMatch[];
  [k: string]: any;
}

export interface IndexSample {
  samples: { face_id: string; crop_url: string; source_url: string | null }[];
  count: number;
}

export interface FaceSearchOpts {
  top_k?: number;
  investigation_id?: string;
  all_faces?: boolean;
  face_index?: number;
}

export const facesApi = {
  search: (file: File, opts: FaceSearchOpts = {}) => {
    const fd = new FormData();
    fd.append("file", file);
    if (opts.top_k != null) fd.append("top_k", String(opts.top_k));
    if (opts.investigation_id) fd.append("investigation_id", opts.investigation_id);
    if (opts.all_faces != null) fd.append("all_faces", String(opts.all_faces));
    if (opts.face_index != null) fd.append("face_index", String(opts.face_index));
    return api.postForm<FaceSearchResult>("/intelligence/face/search", fd);
  },
  discover: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return api.postForm<DiscoverResult>("/intelligence/face/discover", fd);
  },
  indexSample: (limit = 48) => api.get<IndexSample>(`/intelligence/face/index-sample?limit=${limit}`),
};
