import 'intel_models.dart';

/// UsernameHitOut — presence of a handle on one platform.
class UsernameHit {
  final String platform;
  final String name;
  final String username;
  final String url;
  final String status; // found | not_found | unknown | error
  final int? httpStatus;
  final String? checkedAt;

  UsernameHit({
    required this.platform,
    required this.name,
    required this.username,
    required this.url,
    required this.status,
    this.httpStatus,
    this.checkedAt,
  });

  factory UsernameHit.fromJson(Map<String, dynamic> j) => UsernameHit(
        platform: (j['platform'] ?? '').toString(),
        name: (j['name'] ?? '').toString(),
        username: (j['username'] ?? '').toString(),
        url: (j['url'] ?? '').toString(),
        status: (j['status'] ?? 'unknown').toString(),
        httpStatus: (j['http_status'] as num?)?.toInt(),
        checkedAt: j['checked_at'] as String?,
      );
}

/// UsernameIntelligenceOut — per-platform presence plus local matches.
class UsernameIntelligence {
  final String username;
  final List<UsernameHit> results;
  final int foundCount;
  final List<KaiEntity> localEntityMatches;
  final String note;

  UsernameIntelligence({
    required this.username,
    this.results = const [],
    this.foundCount = 0,
    this.localEntityMatches = const [],
    this.note = '',
  });

  factory UsernameIntelligence.fromJson(Map<String, dynamic> j) =>
      UsernameIntelligence(
        username: (j['username'] ?? '').toString(),
        results: ((j['results'] as List?) ?? [])
            .map((e) => UsernameHit.fromJson(e as Map<String, dynamic>))
            .toList(),
        foundCount: (j['found_count'] as num?)?.toInt() ?? 0,
        localEntityMatches: ((j['local_entity_matches'] as List?) ?? [])
            .map((e) => KaiEntity.fromJson(e as Map<String, dynamic>))
            .toList(),
        note: (j['note'] ?? '').toString(),
      );
}
