import 'report_match.dart';

/// One face detected in a single live frame by /intelligence/face/frame.
/// bbox is [x1, y1, x2, y2] in the pixel space of the uploaded JPEG.
/// A [match] is a potential lead, never a confirmed identity.
class LiveFace {
  final List<double> bbox;
  final int? age;
  final String? sex;
  final double quality;
  final double detScore;
  final ReportMatch? match;

  LiveFace({
    required this.bbox,
    this.age,
    this.sex,
    required this.quality,
    required this.detScore,
    this.match,
  });

  factory LiveFace.fromJson(Map<String, dynamic> j) {
    final raw = (j['bbox'] as List?) ?? const [0, 0, 0, 0];
    final b = raw.map((e) => (e as num).toDouble()).toList();
    while (b.length < 4) {
      b.add(0);
    }
    final m = j['match'];
    return LiveFace(
      bbox: b,
      age: (j['age'] as num?)?.toInt(),
      sex: j['sex'] as String?,
      quality: (j['quality'] as num?)?.toDouble() ?? 0,
      detScore: (j['det_score'] as num?)?.toDouble() ?? 0,
      match: m is Map ? ReportMatch.fromJson(Map<String, dynamic>.from(m)) : null,
    );
  }

  double get x1 => bbox[0];
  double get y1 => bbox[1];
  double get x2 => bbox[2];
  double get y2 => bbox[3];
  double get width => (x2 - x1).abs();
  double get height => (y2 - y1).abs();

  /// Short demographic label, e.g. "F · 28" — empty when nothing is known.
  String get demographics {
    final parts = <String>[];
    if (sex != null && sex!.isNotEmpty) parts.add(sex!.toUpperCase());
    if (age != null) parts.add('$age');
    return parts.join(' · ');
  }
}
