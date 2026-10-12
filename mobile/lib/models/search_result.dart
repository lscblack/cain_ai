import 'intel_models.dart';

/// Response of GET /search?q= (SearchResponse).
class SearchResult {
  final String query;
  final String detectedType;
  final String normalized;
  final List<KaiEntity> entityMatches;
  final List<KaiEvidence> evidenceMatches;

  SearchResult({
    required this.query,
    required this.detectedType,
    required this.normalized,
    this.entityMatches = const [],
    this.evidenceMatches = const [],
  });

  factory SearchResult.fromJson(Map<String, dynamic> j) => SearchResult(
        query: (j['query'] ?? '').toString(),
        detectedType: (j['detected_type'] ?? 'unknown').toString(),
        normalized: (j['normalized'] ?? '').toString(),
        entityMatches: ((j['entity_matches'] as List?) ?? [])
            .map((e) => KaiEntity.fromJson(e as Map<String, dynamic>))
            .toList(),
        evidenceMatches: ((j['evidence_matches'] as List?) ?? [])
            .map((e) => KaiEvidence.fromJson(e as Map<String, dynamic>))
            .toList(),
      );
}
