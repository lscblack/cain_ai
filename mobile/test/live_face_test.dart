import 'package:flutter_test/flutter_test.dart';
import 'package:kai_mobile/models/live_face.dart';

void main() {
  group('LiveFace.fromJson', () {
    test('parses a face with a hedged match', () {
      final f = LiveFace.fromJson({
        'bbox': [10, 20, 110, 220],
        'age': 31,
        'sex': 'F',
        'quality': 0.82,
        'det_score': 0.97,
        'match': {
          'face_id': 'abc',
          'similarity_pct': 88.4,
          'band': 'strong_similarity',
          'names': ['Jane Doe'],
        },
      });

      expect(f.x1, 10);
      expect(f.y1, 20);
      expect(f.width, 100);
      expect(f.height, 200);
      expect(f.age, 31);
      expect(f.sex, 'F');
      expect(f.quality, closeTo(0.82, 1e-9));
      expect(f.demographics, 'F · 31');
      expect(f.match, isNotNull);
      expect(f.match!.similarityPct, 88.4);
      expect(f.match!.band, 'strong_similarity');
      expect(f.match!.names.first, 'Jane Doe');
    });

    test('handles a null match and missing demographics', () {
      final f = LiveFace.fromJson({
        'bbox': [0, 0, 50, 60],
        'quality': 0.4,
        'det_score': 0.9,
        'match': null,
      });

      expect(f.match, isNull);
      expect(f.demographics, isEmpty);
      expect(f.width, 50);
    });

    test('tolerates a short/absent bbox', () {
      final f = LiveFace.fromJson({'quality': 0.1, 'det_score': 0.1});
      expect(f.bbox.length, 4);
      expect(f.width, 0);
    });
  });
}
