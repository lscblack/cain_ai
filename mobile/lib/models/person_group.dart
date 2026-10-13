/// Grouped subject models returned by POST /intelligence/face/search in the
/// `people` array. One [Person] = one subject (grouped across result pages);
/// each [Appearance] is one place that subject's face was observed online.
///
/// These are investigative LEADS — never a confirmed identity. The UI keeps
/// the hedged "potential match" wording accordingly.
class Appearance {
  final String faceId;
  final String? cropUrl;
  final String? imageUrl;
  final String? sourceUrl;
  final String? pageTitle;
  final String? caption;
  final String? context;
  final double? similarityPct;
  final String? band;

  Appearance({
    required this.faceId,
    this.cropUrl,
    this.imageUrl,
    this.sourceUrl,
    this.pageTitle,
    this.caption,
    this.context,
    this.similarityPct,
    this.band,
  });

  factory Appearance.fromJson(Map<String, dynamic> j) => Appearance(
        faceId: (j['face_id'] ?? '').toString(),
        cropUrl: j['crop_url'] as String?,
        imageUrl: j['image_url'] as String?,
        sourceUrl: j['source_url'] as String?,
        pageTitle: j['page_title'] as String?,
        caption: j['caption'] as String?,
        context: j['context'] as String?,
        similarityPct: (j['similarity_pct'] as num?)?.toDouble(),
        band: j['band'] as String?,
      );

  /// Host of the source URL (www. stripped), or a friendly fallback label.
  String get sourceDomain {
    final u = sourceUrl;
    if (u == null || u.isEmpty) return 'unknown source';
    final uri = Uri.tryParse(u);
    if (uri == null || uri.host.isEmpty) return u;
    return uri.host.replaceFirst(RegExp(r'^www\.'), '');
  }

  /// Short label for the source page/event: page title if present, else domain.
  String get label {
    final t = pageTitle;
    if (t != null && t.trim().isNotEmpty) return t.trim();
    return sourceDomain;
  }
}

class Person {
  final String personId;
  final String? name;
  final List<String> names;
  final List<String> emails;
  final List<String> phones;
  final List<String> usernames;
  final List<String> titles;
  final List<String> orgs;
  final List<String> locations;
  final int? age;
  final String? sex;
  final double? similarityPct;
  final String? band;
  final String? cropUrl;
  final int appearanceCount;
  final List<String> contexts;
  final String? description;
  final List<Appearance> appearances;

  Person({
    required this.personId,
    this.name,
    this.names = const [],
    this.emails = const [],
    this.phones = const [],
    this.usernames = const [],
    this.titles = const [],
    this.orgs = const [],
    this.locations = const [],
    this.age,
    this.sex,
    this.similarityPct,
    this.band,
    this.cropUrl,
    this.appearanceCount = 0,
    this.contexts = const [],
    this.description,
    this.appearances = const [],
  });

  static List<String> _strList(dynamic v) => v is List
      ? v.map((e) => e.toString()).where((s) => s.trim().isNotEmpty).toList()
      : const [];

  factory Person.fromJson(Map<String, dynamic> j) {
    final appearances = (j['appearances'] as List? ?? const [])
        .whereType<Map>()
        .map((a) => Appearance.fromJson(a.cast<String, dynamic>()))
        .toList();
    return Person(
      personId: (j['person_id'] ?? '').toString(),
      name: j['name'] as String?,
      names: _strList(j['names']),
      emails: _strList(j['emails']),
      phones: _strList(j['phones']),
      usernames: _strList(j['usernames']),
      titles: _strList(j['titles']),
      orgs: _strList(j['orgs']),
      locations: _strList(j['locations']),
      age: (j['age'] as num?)?.toInt(),
      sex: j['sex'] as String?,
      similarityPct: (j['similarity_pct'] as num?)?.toDouble(),
      band: j['band'] as String?,
      cropUrl: j['crop_url'] as String?,
      appearanceCount:
          (j['appearance_count'] as num?)?.toInt() ?? appearances.length,
      contexts: _strList(j['contexts']),
      description: j['description'] as String?,
      appearances: appearances,
    );
  }

  static List<Person> listFromJson(dynamic v) => v is List
      ? v
          .whereType<Map>()
          .map((p) => Person.fromJson(p.cast<String, dynamic>()))
          .toList()
      : const [];

  String get displayName {
    final n = name;
    if (n != null && n.trim().isNotEmpty) return n.trim();
    if (names.isNotEmpty) return names.first;
    return 'Unknown subject';
  }
}
