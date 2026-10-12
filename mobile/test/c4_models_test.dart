import 'package:flutter_test/flutter_test.dart';

import 'package:kai_mobile/models/email_intel.dart';
import 'package:kai_mobile/models/intel_models.dart';
import 'package:kai_mobile/models/investigation.dart';
import 'package:kai_mobile/models/phone_intel.dart';
import 'package:kai_mobile/models/search_result.dart';
import 'package:kai_mobile/models/username_intel.dart';

void main() {
  test('KaiEntity / KaiEvidence parse from JSON', () {
    final e = KaiEntity.fromJson({
      'id': 'e1',
      'investigation_id': 'inv1',
      'type': 'phone',
      'value': '+250788123456',
      'label': 'subject cell',
      'metadata': {'source': 'crawl'},
    });
    expect(e.type, 'phone');
    expect(e.value, '+250788123456');
    expect(e.label, 'subject cell');
    expect(e.metadata['source'], 'crawl');

    final ev = KaiEvidence.fromJson({
      'id': 'v1',
      'investigation_id': 'inv1',
      'type': 'url',
      'source_url': 'https://example.com/profile',
      'confidence': 0.7,
      'band': 'potential_match',
    });
    expect(ev.sourceUrl, 'https://example.com/profile');
    expect(ev.confidence, 0.7);
    expect(ev.band, 'potential_match');
  });

  test('SearchResult parses detected type and matches', () {
    final r = SearchResult.fromJson({
      'query': '+250788123456',
      'detected_type': 'phone',
      'normalized': '250788123456',
      'entity_matches': [
        {'id': 'e1', 'type': 'phone', 'value': '+250788123456'}
      ],
      'evidence_matches': [
        {'id': 'v1', 'type': 'url', 'source_url': 'https://x.test'}
      ],
    });
    expect(r.detectedType, 'phone');
    expect(r.normalized, '250788123456');
    expect(r.entityMatches.single.value, '+250788123456');
    expect(r.evidenceMatches.single.sourceUrl, 'https://x.test');
  });

  test('SearchResult tolerates missing lists', () {
    final r = SearchResult.fromJson({
      'query': 'x',
      'detected_type': 'unknown',
      'normalized': 'x',
    });
    expect(r.entityMatches, isEmpty);
    expect(r.evidenceMatches, isEmpty);
  });

  test('PhoneIntelligence parses analysis + variants + note', () {
    final p = PhoneIntelligence.fromJson({
      'analysis': {
        'input': '+250788123456',
        'parsed': true,
        'valid': true,
        'possible': true,
        'e164': '+250788123456',
        'international': '+250 788 123 456',
        'national': '078 812 3456',
        'country_code': 250,
        'region': 'RW',
        'location': 'Rwanda',
        'carrier': 'MTN',
        'number_type': 'mobile',
        'variants': ['+250788123456', '0788123456'],
        'error': null,
      },
      'local_entity_matches': [],
      'local_evidence_matches': [],
      'note': 'Metadata describes the number only.',
    });
    expect(p.analysis.valid, isTrue);
    expect(p.analysis.countryCode, 250);
    expect(p.analysis.carrier, 'MTN');
    expect(p.analysis.variants.length, 2);
    expect(p.note, contains('Metadata'));
  });

  test('PhoneAnalysis handles unparseable input', () {
    final a = PhoneAnalysis.fromJson({
      'input': 'nope',
      'parsed': false,
      'valid': false,
      'possible': false,
      'number_type': 'unknown',
      'error': 'not_a_number',
    });
    expect(a.parsed, isFalse);
    expect(a.error, 'not_a_number');
    expect(a.variants, isEmpty);
  });

  test('EmailIntelligence parses DNS signals and derived usernames', () {
    final em = EmailIntelligence.fromJson({
      'analysis': {
        'input': 'john.doe@example.com',
        'valid_format': true,
        'local': 'john.doe',
        'domain': 'example.com',
        'gravatar_url': 'https://gravatar.com/avatar/abc',
        'derived_usernames': ['johndoe', 'john.doe', 'jdoe'],
        'mx_records': ['mail.example.com'],
        'has_mx': true,
        'spf': 'v=spf1 -all',
        'dmarc': 'v=DMARC1',
        'dns_checked': true,
        'notes': ['corporate domain'],
      },
      'local_entity_matches': [],
      'local_evidence_matches': [],
      'note': 'DNS/MX/SPF/DMARC',
    });
    expect(em.analysis.hasMx, isTrue);
    expect(em.analysis.derivedUsernames, contains('jdoe'));
    expect(em.analysis.mxRecords.first, 'mail.example.com');
    expect(em.analysis.gravatarUrl, isNotNull);
  });

  test('UsernameIntelligence parses per-platform hits', () {
    final u = UsernameIntelligence.fromJson({
      'username': 'osint_guy',
      'results': [
        {
          'platform': 'github',
          'name': 'GitHub',
          'username': 'osint_guy',
          'url': 'https://github.com/osint_guy',
          'status': 'found',
          'http_status': 200,
          'checked_at': '2026-01-01T00:00:00Z',
        },
        {
          'platform': 'twitter',
          'name': 'Twitter',
          'username': 'osint_guy',
          'url': 'https://twitter.com/osint_guy',
          'status': 'not_found',
          'http_status': 404,
          'checked_at': '2026-01-01T00:00:00Z',
        },
      ],
      'found_count': 1,
      'local_entity_matches': [],
      'note': 'A reachable public profile is an observation.',
    });
    expect(u.results.length, 2);
    expect(u.foundCount, 1);
    expect(u.results.first.status, 'found');
    expect(u.results.first.httpStatus, 200);
  });

  test('InvestigationDetail parses counts', () {
    final d = InvestigationDetail.fromJson({
      'id': 'inv1',
      'code': 'KAI-001',
      'name': 'Subject 001',
      'description': 'test case',
      'status': 'open',
      'created_at': '2026-01-01T00:00:00Z',
      'updated_at': '2026-01-02T00:00:00Z',
      'entity_count': 3,
      'evidence_count': 5,
      'relationship_count': 2,
    });
    expect(d.code, 'KAI-001');
    expect(d.entityCount, 3);
    expect(d.evidenceCount, 5);
    expect(d.relationshipCount, 2);
    expect(d.status, 'open');
  });
}
