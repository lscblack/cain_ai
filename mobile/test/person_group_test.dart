import 'package:flutter_test/flutter_test.dart';

import 'package:kai_mobile/models/person_group.dart';

void main() {
  test('Person parses grouped subject + appearances from JSON', () {
    final people = Person.listFromJson([
      {
        'person_id': 'p1',
        'name': 'Loue Sauveur Christian',
        'names': ['Loue Sauveur Christian', 'L. Christian'],
        'emails': ['x@example.com'],
        'titles': ['Engineer'],
        'orgs': ['KAI'],
        'locations': ['Kigali'],
        'age': 38,
        'sex': 'M',
        'similarity_pct': 59.9,
        'band': 'potential_match',
        'crop_url': '/crops/p1.jpg',
        'appearance_count': 2,
        'contexts': ['Seen speaking at a conference.'],
        'appearances': [
          {
            'face_id': 'f1',
            'crop_url': '/crops/f1.jpg',
            'source_url': 'https://www.example.com/story',
            'page_title': 'Conference 2024',
            'caption': 'On stage',
            'similarity_pct': 61.0,
            'band': 'potential_match',
          },
          {
            'face_id': 'f2',
            'source_url': 'https://news.site/article',
            'similarity_pct': 55.0,
            'band': 'possible_association',
          },
        ],
      },
    ]);

    expect(people.length, 1);
    final p = people.first;
    expect(p.displayName, 'Loue Sauveur Christian');
    expect(p.appearanceCount, 2);
    expect(p.appearances.length, 2);
    expect(p.names.length, 2);
    expect(p.contexts.first, 'Seen speaking at a conference.');

    // page_title wins for label; www. stripped for domain fallback.
    expect(p.appearances.first.label, 'Conference 2024');
    expect(p.appearances.first.sourceDomain, 'example.com');
    // no page_title -> domain used as label.
    expect(p.appearances[1].label, 'news.site');
  });

  test('Person falls back to names, then Unknown subject', () {
    final noName = Person.fromJson({
      'person_id': 'p2',
      'names': ['J. Doe'],
    });
    expect(noName.displayName, 'J. Doe');

    final anon = Person.fromJson({'person_id': 'p3'});
    expect(anon.displayName, 'Unknown subject');
    expect(anon.appearanceCount, 0);
  });
}
