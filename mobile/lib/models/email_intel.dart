import 'intel_models.dart';

/// EmailAnalysisOut — direct signals about the address and domain.
class EmailAnalysis {
  final String input;
  final bool validFormat;
  final String? local;
  final String? domain;
  final String? gravatarUrl;
  final List<String> derivedUsernames;
  final List<String> mxRecords;
  final bool? hasMx;
  final String? spf;
  final String? dmarc;
  final bool dnsChecked;
  final List<String> notes;

  EmailAnalysis({
    required this.input,
    required this.validFormat,
    this.local,
    this.domain,
    this.gravatarUrl,
    this.derivedUsernames = const [],
    this.mxRecords = const [],
    this.hasMx,
    this.spf,
    this.dmarc,
    this.dnsChecked = false,
    this.notes = const [],
  });

  factory EmailAnalysis.fromJson(Map<String, dynamic> j) => EmailAnalysis(
        input: (j['input'] ?? '').toString(),
        validFormat: j['valid_format'] == true,
        local: j['local'] as String?,
        domain: j['domain'] as String?,
        gravatarUrl: j['gravatar_url'] as String?,
        derivedUsernames: stringList(j['derived_usernames']),
        mxRecords: stringList(j['mx_records']),
        hasMx: j['has_mx'] as bool?,
        spf: j['spf'] as String?,
        dmarc: j['dmarc'] as String?,
        dnsChecked: j['dns_checked'] == true,
        notes: stringList(j['notes']),
      );
}

/// EmailIntelligenceOut — analysis plus local corpus matches.
class EmailIntelligence {
  final EmailAnalysis analysis;
  final List<KaiEntity> localEntityMatches;
  final List<KaiEvidence> localEvidenceMatches;
  final String note;

  EmailIntelligence({
    required this.analysis,
    this.localEntityMatches = const [],
    this.localEvidenceMatches = const [],
    this.note = '',
  });

  factory EmailIntelligence.fromJson(Map<String, dynamic> j) => EmailIntelligence(
        analysis:
            EmailAnalysis.fromJson((j['analysis'] as Map).cast<String, dynamic>()),
        localEntityMatches: ((j['local_entity_matches'] as List?) ?? [])
            .map((e) => KaiEntity.fromJson(e as Map<String, dynamic>))
            .toList(),
        localEvidenceMatches: ((j['local_evidence_matches'] as List?) ?? [])
            .map((e) => KaiEvidence.fromJson(e as Map<String, dynamic>))
            .toList(),
        note: (j['note'] ?? '').toString(),
      );
}
