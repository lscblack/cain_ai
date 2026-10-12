/// One ranked face match / person dossier returned by /intelligence/face/search.
class ReportMatch {
  final String faceId;
  final double? similarityPct;
  final String? band;
  final String? cropUrl;
  final List<String> names;
  final List<String> emails;
  final List<String> phones;
  final List<String> usernames;
  final List<String> titles;
  final List<String> orgs;
  final List<String> locations;
  final int? age;
  final String? sex;
  final String? description;
  final String? caption;
  final String? pageTitle;
  final String? sourceUrl;

  ReportMatch({
    required this.faceId,
    this.similarityPct,
    this.band,
    this.cropUrl,
    this.names = const [],
    this.emails = const [],
    this.phones = const [],
    this.usernames = const [],
    this.titles = const [],
    this.orgs = const [],
    this.locations = const [],
    this.age,
    this.sex,
    this.description,
    this.caption,
    this.pageTitle,
    this.sourceUrl,
  });

  static List<String> _strList(dynamic v) =>
      v is List ? v.map((e) => e.toString()).toList() : const [];

  factory ReportMatch.fromJson(Map<String, dynamic> j) => ReportMatch(
        faceId: (j['face_id'] ?? '').toString(),
        similarityPct: (j['similarity_pct'] as num?)?.toDouble(),
        band: j['band'] as String?,
        cropUrl: j['crop_url'] as String?,
        names: _strList(j['names']),
        emails: _strList(j['emails']),
        phones: _strList(j['phones']),
        usernames: _strList(j['usernames']),
        titles: _strList(j['titles']),
        orgs: _strList(j['orgs']),
        locations: _strList(j['locations']),
        age: (j['age'] as num?)?.toInt(),
        sex: j['sex'] as String?,
        description: j['description'] as String?,
        caption: j['caption'] as String?,
        pageTitle: j['page_title'] as String?,
        sourceUrl: j['source_url'] as String?,
      );

  String get displayName =>
      names.isNotEmpty ? names.first : (pageTitle ?? 'Unknown subject');
}
