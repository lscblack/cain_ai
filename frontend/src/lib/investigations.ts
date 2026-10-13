import { api } from "@/lib/api";
import type {
  CaseGraph,
  Suggestion,
  EntityNode,
  EntityType,
  EvidenceItem,
  Investigation,
  InvestigationDetail,
  RelationshipEdge,
} from "@/types";

export const investigationsApi = {
  list: () => api.get<InvestigationDetail[]>("/investigations"),
  get: (id: string) => api.get<InvestigationDetail>(`/investigations/${id}`),
  create: (name: string, description?: string) =>
    api.post<Investigation>("/investigations", { name, description }),
  remove: (id: string) => api.del<void>(`/investigations/${id}`),
  removeDiscovery: (runId: string) => api.del<void>(`/discovery/investigations/${runId}`),

  entities: (id: string) => api.get<EntityNode[]>(`/investigations/${id}/entities`),
  addEntity: (id: string, body: { type: EntityType; value: string; label?: string }) =>
    api.post<EntityNode>(`/investigations/${id}/entities`, body),

  evidence: (id: string) => api.get<EvidenceItem[]>(`/investigations/${id}/evidence`),
  addEvidence: (
    id: string,
    body: { type: EntityType; source_url: string; confidence?: number; band?: string },
  ) => api.post<EvidenceItem>(`/investigations/${id}/evidence`, body),

  relationships: (id: string) =>
    api.get<RelationshipEdge[]>(`/investigations/${id}/relationships`).catch(() => [] as RelationshipEdge[]),
  addRelationship: (
    id: string,
    body: {
      source_entity_id: string;
      target_entity_id: string;
      rel_type: string;
      source_url: string;
    },
  ) => api.post<RelationshipEdge>(`/investigations/${id}/relationships`, body),

  graph: (id: string) => api.get<CaseGraph>(`/investigations/${id}/graph`),
  correlations: (id: string) =>
    api.get<{ suggestions: Suggestion[] }>(`/investigations/${id}/correlations`),
};
