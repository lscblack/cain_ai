import 'package:flutter_test/flutter_test.dart';

import 'package:kai_mobile/models/report_match.dart';

void main() {
  test('ReportMatch parses report-card fields from JSON', () {
    final m = ReportMatch.fromJson({
      'face_id': 'abc123def456',
      'similarity_pct': 59.9,
      'band': 'potential_match',
      'names': ['Loue Sauveur Christian', 'L. Christian'],
      'emails': ['x@example.com'],
      'titles': ['Engineer'],
      'orgs': ['KAI'],
      'age': 38,
      'sex': 'M',
    });
    expect(m.displayName, 'Loue Sauveur Christian');
    expect(m.band, 'potential_match');
    expect(m.age, 38);
    expect(m.titles.first, 'Engineer');
    expect(m.names.length, 2);
  });
}
