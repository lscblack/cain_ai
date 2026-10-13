import 'person_group.dart';

/// One detected face in a multi-face "Detect Faces" scan
/// (POST /intelligence/face/search with all_faces=true).
///
/// Each face carries its pixel-space [bbox] (so the UI can draw a numbered box
/// over the uploaded image), light demographics/quality, and the grouped
/// [people] it was searched against the index for. Every person is a LEAD —
/// the UI keeps the hedged "potential match" wording, never a confirmed ID.
class DetectedFace {
  final int faceIndex;

  /// [x1, y1, x2, y2] in the ORIGINAL uploaded image's pixel coordinates.
  final List<double> bbox;
  final int? age;
  final String? sex;
  final double? quality;
  final double? detScore;
  final int matchCount;
  final List<Person> people;

  DetectedFace({
    required this.faceIndex,
    required this.bbox,
    this.age,
    this.sex,
    this.quality,
    this.detScore,
    this.matchCount = 0,
    this.people = const [],
  });

  static List<double> _bbox(dynamic v) {
    if (v is List && v.length >= 4) {
      return v.take(4).map((e) => (e as num).toDouble()).toList();
    }
    return const [0, 0, 0, 0];
  }

  factory DetectedFace.fromJson(Map<String, dynamic> j) {
    final people = Person.listFromJson(j['people']);
    return DetectedFace(
      faceIndex: (j['face_index'] as num?)?.toInt() ?? 0,
      bbox: _bbox(j['bbox']),
      age: (j['age'] as num?)?.toInt(),
      sex: j['sex'] as String?,
      quality: (j['quality'] as num?)?.toDouble(),
      detScore: (j['det_score'] as num?)?.toDouble(),
      matchCount: (j['match_count'] as num?)?.toInt() ?? people.length,
      people: people,
    );
  }

  static List<DetectedFace> listFromJson(dynamic v) => v is List
      ? v
          .whereType<Map>()
          .map((f) => DetectedFace.fromJson(f.cast<String, dynamic>()))
          .toList()
      : const [];

  /// Human label for the overlay box / card header ("FACE 1").
  String get label => 'FACE ${faceIndex + 1}';

  bool get hasMatches => people.isNotEmpty;

  /// "~38y · M" style demographic summary, or null when nothing is known.
  String? get demographics {
    final parts = <String>[
      if ((age ?? 0) > 0) '~${age}y',
      if (sex != null && sex!.isNotEmpty) sex!,
    ];
    return parts.isEmpty ? null : parts.join(' · ');
  }
}
