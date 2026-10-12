/// Shared intelligence models — entities and evidence are returned by the
/// universal search, the phone/email/username tools, and investigations, so
/// they live here and are reused everywhere.
library;

List<String> stringList(dynamic v) =>
    v is List ? v.map((e) => e.toString()).toList() : const [];

/// A graph entity (EntityOut) — a phone, email, username, face, etc. held in
/// the local corpus.
class KaiEntity {
  final String id;
  final String? investigationId;
  final String type;
  final String value;
  final String? label;
  final Map<String, dynamic> metadata;

  KaiEntity({
    required this.id,
    this.investigationId,
    required this.type,
    required this.value,
    this.label,
    this.metadata = const {},
  });

  factory KaiEntity.fromJson(Map<String, dynamic> j) => KaiEntity(
        id: (j['id'] ?? '').toString(),
        investigationId: j['investigation_id']?.toString(),
        type: (j['type'] ?? '').toString(),
        value: (j['value'] ?? '').toString(),
        label: j['label'] as String?,
        metadata: (j['metadata'] as Map?)?.cast<String, dynamic>() ?? const {},
      );
}

/// A piece of evidence (EvidenceOut) — an observed source URL with confidence /
/// band metadata.
class KaiEvidence {
  final String id;
  final String? investigationId;
  final String? entityId;
  final String type;
  final String sourceUrl;
  final String? collectedAt;
  final double? confidence;
  final String? band;

  KaiEvidence({
    required this.id,
    this.investigationId,
    this.entityId,
    required this.type,
    required this.sourceUrl,
    this.collectedAt,
    this.confidence,
    this.band,
  });

  factory KaiEvidence.fromJson(Map<String, dynamic> j) => KaiEvidence(
        id: (j['id'] ?? '').toString(),
        investigationId: j['investigation_id']?.toString(),
        entityId: j['entity_id']?.toString(),
        type: (j['type'] ?? '').toString(),
        sourceUrl: (j['source_url'] ?? '').toString(),
        collectedAt: j['collected_at'] as String?,
        confidence: (j['confidence'] as num?)?.toDouble(),
        band: j['band'] as String?,
      );
}
