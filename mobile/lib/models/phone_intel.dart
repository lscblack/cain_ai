import 'intel_models.dart';

/// PhoneAnalysisOut — metadata about the number itself.
class PhoneAnalysis {
  final String input;
  final bool parsed;
  final bool valid;
  final bool possible;
  final String? e164;
  final String? international;
  final String? national;
  final int? countryCode;
  final String? region;
  final String? location;
  final String? carrier;
  final String numberType;
  final List<String> variants;
  final String? error;

  PhoneAnalysis({
    required this.input,
    required this.parsed,
    required this.valid,
    required this.possible,
    this.e164,
    this.international,
    this.national,
    this.countryCode,
    this.region,
    this.location,
    this.carrier,
    this.numberType = 'unknown',
    this.variants = const [],
    this.error,
  });

  factory PhoneAnalysis.fromJson(Map<String, dynamic> j) => PhoneAnalysis(
        input: (j['input'] ?? '').toString(),
        parsed: j['parsed'] == true,
        valid: j['valid'] == true,
        possible: j['possible'] == true,
        e164: j['e164'] as String?,
        international: j['international'] as String?,
        national: j['national'] as String?,
        countryCode: (j['country_code'] as num?)?.toInt(),
        region: j['region'] as String?,
        location: j['location'] as String?,
        carrier: j['carrier'] as String?,
        numberType: (j['number_type'] ?? 'unknown').toString(),
        variants: stringList(j['variants']),
        error: j['error'] as String?,
      );
}

/// PhoneIntelligenceOut — analysis plus local corpus matches.
class PhoneIntelligence {
  final PhoneAnalysis analysis;
  final List<KaiEntity> localEntityMatches;
  final List<KaiEvidence> localEvidenceMatches;
  final String note;

  PhoneIntelligence({
    required this.analysis,
    this.localEntityMatches = const [],
    this.localEvidenceMatches = const [],
    this.note = '',
  });

  factory PhoneIntelligence.fromJson(Map<String, dynamic> j) => PhoneIntelligence(
        analysis:
            PhoneAnalysis.fromJson((j['analysis'] as Map).cast<String, dynamic>()),
        localEntityMatches: ((j['local_entity_matches'] as List?) ?? [])
            .map((e) => KaiEntity.fromJson(e as Map<String, dynamic>))
            .toList(),
        localEvidenceMatches: ((j['local_evidence_matches'] as List?) ?? [])
            .map((e) => KaiEvidence.fromJson(e as Map<String, dynamic>))
            .toList(),
        note: (j['note'] ?? '').toString(),
      );
}
