import 'package:flutter_test/flutter_test.dart';

import 'package:kai_mobile/screens/video_search_screen.dart';

void main() {
  test('VideoPerson parses a person entry + nested matches', () {
    final p = VideoPerson.fromJson({
      'age': 42,
      'sex': 'M',
      'quality': 0.81,
      'frames_seen': 3,
      'matches': [
        {
          'face_id': 'abc123def456',
          'similarity_pct': 97.2,
          'band': 'potential_match',
          'names': ['Abraham Lincoln'],
        },
      ],
    });
    expect(p.age, 42);
    expect(p.sex, 'M');
    expect(p.quality, 0.81);
    expect(p.framesSeen, 3);
    expect(p.matches.length, 1);
    expect(p.matches.first.displayName, 'Abraham Lincoln');
  });

  test('VideoPerson tolerates missing/empty fields', () {
    final p = VideoPerson.fromJson({});
    expect(p.age, isNull);
    expect(p.sex, isNull);
    expect(p.framesSeen, 0);
    expect(p.matches, isEmpty);
  });
}
