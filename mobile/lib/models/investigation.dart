/// InvestigationDetail — a case plus its entity/evidence/relationship counts.
/// Returned by GET /investigations (list) and GET /investigations/{id}.
class InvestigationDetail {
  final String id;
  final String code;
  final String name;
  final String? description;
  final String status; // open | archived
  final String? createdAt;
  final String? updatedAt;
  final int entityCount;
  final int evidenceCount;
  final int relationshipCount;

  InvestigationDetail({
    required this.id,
    required this.code,
    required this.name,
    this.description,
    this.status = 'open',
    this.createdAt,
    this.updatedAt,
    this.entityCount = 0,
    this.evidenceCount = 0,
    this.relationshipCount = 0,
  });

  factory InvestigationDetail.fromJson(Map<String, dynamic> j) =>
      InvestigationDetail(
        id: (j['id'] ?? '').toString(),
        code: (j['code'] ?? '').toString(),
        name: (j['name'] ?? '').toString(),
        description: j['description'] as String?,
        status: (j['status'] ?? 'open').toString(),
        createdAt: j['created_at'] as String?,
        updatedAt: j['updated_at'] as String?,
        entityCount: (j['entity_count'] as num?)?.toInt() ?? 0,
        evidenceCount: (j['evidence_count'] as num?)?.toInt() ?? 0,
        relationshipCount: (j['relationship_count'] as num?)?.toInt() ?? 0,
      );
}
