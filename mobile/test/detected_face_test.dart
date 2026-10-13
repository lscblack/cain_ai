import 'package:flutter_test/flutter_test.dart';

import 'package:kai_mobile/models/detected_face.dart';

void main() {
  test('DetectedFace parses multi-face all_faces=true response', () {
    final faces = DetectedFace.listFromJson([
      {
        'face_index': 0,
        'bbox': [10, 20, 110, 220],
        'age': 38,
        'sex': 'M',
        'quality': 0.91,
        'det_score': 0.88,
        'match_count': 2,
        'people': [
          {
            'person_id': 'p1',
            'name': 'Loue Sauveur Christian',
            'similarity_pct': 61.0,
            'band': 'potential_match',
            'crop_url': '/crops/p1.jpg',
            'appearance_count': 3,
            'appearances': [
              {
                'face_id': 'f1',
                'crop_url': '/crops/f1.jpg',
                'source_url': 'https://www.example.com/story',
                'page_title': 'Conference 2024',
                'similarity_pct': 61.0,
                'band': 'potential_match',
              },
            ],
          },
          {'person_id': 'p2', 'similarity_pct': 40.0, 'band': 'possible_association'},
        ],
      },
      {
        'face_index': 1,
        'bbox': [300, 40, 380, 150],
        'quality': 0.5,
        'match_count': 0,
        'people': [],
      },
    ]);

    expect(faces.length, 2);

    final f0 = faces.first;
    expect(f0.faceIndex, 0);
    expect(f0.label, 'FACE 1');
    expect(f0.bbox, [10.0, 20.0, 110.0, 220.0]);
    expect(f0.age, 38);
    expect(f0.demographics, '~38y · M');
    expect(f0.hasMatches, isTrue);
    expect(f0.matchCount, 2);
    expect(f0.people.first.displayName, 'Loue Sauveur Christian');
    expect(f0.people.first.appearances.length, 1);

    final f1 = faces[1];
    expect(f1.hasMatches, isFalse);
    expect(f1.people, isEmpty);
    expect(f1.label, 'FACE 2');
  });

  test('DetectedFace tolerates missing/short bbox and empty input', () {
    expect(DetectedFace.listFromJson(null), isEmpty);
    final f = DetectedFace.fromJson({'face_index': 0});
    expect(f.bbox, [0.0, 0.0, 0.0, 0.0]);
    expect(f.demographics, isNull);
    expect(f.hasMatches, isFalse);
  });
}
