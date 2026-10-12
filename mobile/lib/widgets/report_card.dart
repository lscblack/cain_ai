import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../models/report_match.dart';
import '../services/api_client.dart';
import '../theme/hacker_theme.dart';

/// Person "dossier" card: matched face image beside known attributes.
/// Matches are potential leads — never a confirmed identity.
class ReportCard extends StatelessWidget {
  final ReportMatch m;
  const ReportCard({super.key, required this.m});

  @override
  Widget build(BuildContext context) {
    final color = KaiColors.band(m.band);
    final job = [m.titles.isNotEmpty ? m.titles.first : null, m.orgs.isNotEmpty ? m.orgs.first : null]
        .whereType<String>()
        .join(' · ');
    final bio = (m.description?.isNotEmpty ?? false)
        ? m.description
        : (m.caption?.isNotEmpty ?? false ? m.caption : null);

    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      decoration: BoxDecoration(
        color: KaiColors.panel,
        border: Border.all(color: KaiColors.line),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // header band
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
            decoration: const BoxDecoration(
              color: KaiColors.panel2,
              border: Border(bottom: BorderSide(color: KaiColors.line)),
              borderRadius: BorderRadius.vertical(top: Radius.circular(10)),
            ),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text(
                  'DOSSIER · ${m.faceId.length >= 8 ? m.faceId.substring(0, 8) : m.faceId}',
                  style: const TextStyle(color: KaiColors.muted, fontSize: 11),
                ),
                Row(children: [
                  if (m.similarityPct != null)
                    Text('${m.similarityPct}%',
                        style: const TextStyle(fontSize: 14, color: KaiColors.ink)),
                  const SizedBox(width: 8),
                  Text(KaiColors.bandLabel(m.band),
                      style: TextStyle(color: color, fontSize: 11, letterSpacing: 0.5)),
                ]),
              ],
            ),
          ),
          Padding(
            padding: const EdgeInsets.all(12),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                ClipRRect(
                  borderRadius: BorderRadius.circular(6),
                  child: Container(
                    width: 120,
                    height: 120,
                    decoration: BoxDecoration(border: Border.all(color: color)),
                    child: m.cropUrl != null
                        ? Image.network(
                            ApiClient.instance.imageUrl(m.cropUrl!),
                            headers: ApiClient.instance.imageHeaders,
                            fit: BoxFit.cover,
                            errorBuilder: (_, _, _) => const _NoFace(),
                          )
                        : const _NoFace(),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(m.displayName,
                          style: const TextStyle(
                              fontSize: 16, fontWeight: FontWeight.bold, color: KaiColors.ink)),
                      const SizedBox(height: 2),
                      Text(
                        [
                          m.sex,
                          (m.age ?? 0) > 0 ? '~${m.age}y' : null
                        ].whereType<String>().join(' · ').isEmpty
                            ? 'age/sex n/a'
                            : [m.sex, (m.age ?? 0) > 0 ? '~${m.age}y' : null]
                                .whereType<String>()
                                .join(' · '),
                        style: const TextStyle(color: KaiColors.muted, fontSize: 11),
                      ),
                      if (m.names.length > 1) ...[
                        const SizedBox(height: 6),
                        Wrap(
                          spacing: 4,
                          runSpacing: 4,
                          children: m.names.skip(1).take(5).map((a) {
                            return Container(
                              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                              decoration: BoxDecoration(
                                border: Border.all(color: KaiColors.line),
                                borderRadius: BorderRadius.circular(4),
                              ),
                              child: Text(a,
                                  style: const TextStyle(color: KaiColors.warn, fontSize: 11)),
                            );
                          }).toList(),
                        ),
                      ],
                      if (job.isNotEmpty) _field(Icons.work_outline, 'JOB / TITLE', [job]),
                      _field(Icons.place_outlined, 'LOCATION', m.locations),
                      if (bio != null) ...[
                        const SizedBox(height: 8),
                        Container(
                          padding: const EdgeInsets.all(8),
                          decoration: const BoxDecoration(
                            color: KaiColors.panel2,
                            border: Border(left: BorderSide(color: KaiColors.accent, width: 2)),
                          ),
                          child: Text(bio,
                              style: const TextStyle(color: KaiColors.muted, fontSize: 11, height: 1.4)),
                        ),
                      ],
                      _field(Icons.alternate_email, 'EMAILS', m.emails),
                      _field(Icons.phone_outlined, 'PHONES', m.phones),
                      _field(Icons.person_outline, 'SOCIAL', m.usernames),
                    ],
                  ),
                ),
              ],
            ),
          ),
          if (m.sourceUrl != null)
            Padding(
              padding: const EdgeInsets.fromLTRB(12, 0, 12, 12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Divider(color: KaiColors.line, height: 16),
                  const Text('SOURCES',
                      style: TextStyle(color: KaiColors.muted, fontSize: 10, letterSpacing: 1)),
                  const SizedBox(height: 4),
                  InkWell(
                    onTap: () => _open(m.sourceUrl!),
                    child: Text(m.pageTitle ?? m.sourceUrl!,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(color: KaiColors.verified, fontSize: 12)),
                  ),
                ],
              ),
            ),
          _ConnectionsSection(faceId: m.faceId),
        ],
      ),
    );
  }

  Widget _field(IconData icon, String label, List<String> values) {
    if (values.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(top: 8),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, size: 14, color: KaiColors.muted),
          const SizedBox(width: 6),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(label,
                    style: const TextStyle(color: KaiColors.muted, fontSize: 10, letterSpacing: 1)),
                Text(values.join('   '),
                    style: const TextStyle(color: KaiColors.ink, fontSize: 13)),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Future<void> _open(String url) async {
    final uri = Uri.tryParse(url);
    if (uri != null && await canLaunchUrl(uri)) {
      await launchUrl(uri, mode: LaunchMode.externalApplication);
    }
  }
}

class _NoFace extends StatelessWidget {
  const _NoFace();
  @override
  Widget build(BuildContext context) => Container(
        color: KaiColors.panel2,
        child: const Icon(Icons.person, color: KaiColors.muted, size: 28),
      );
}

/// Lazy-loaded "Connected people" — associates via public co-occurrence.
class _ConnectionsSection extends StatefulWidget {
  final String faceId;
  const _ConnectionsSection({required this.faceId});

  @override
  State<_ConnectionsSection> createState() => _ConnectionsSectionState();
}

class _ConnectionsSectionState extends State<_ConnectionsSection> {
  bool _open = false;
  bool _loading = false;
  List<Map<String, dynamic>>? _conns;

  String _reasonLabel(String r) {
    if (r == 'co_located') return 'same page';
    if (r.startsWith('shares:')) return 'shares ${r.substring(7)}';
    return r;
  }

  Future<void> _load() async {
    setState(() => _open = true);
    if (_conns != null || _loading) return;
    setState(() => _loading = true);
    try {
      final r = await ApiClient.instance
          .getJson('/intelligence/face/${widget.faceId}/connections');
      if (r.statusCode == 200) {
        final list = (jsonDecode(r.body)['connections'] as List? ?? [])
            .map((e) => (e as Map).cast<String, dynamic>())
            .toList();
        setState(() => _conns = list);
      } else {
        setState(() => _conns = []);
      }
    } catch (_) {
      setState(() => _conns = []);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(12, 8, 12, 12),
      decoration: const BoxDecoration(
        border: Border(top: BorderSide(color: KaiColors.line)),
      ),
      child: !_open
          ? InkWell(
              onTap: _load,
              child: const Row(children: [
                Icon(Icons.groups_outlined, size: 15, color: KaiColors.verified),
                SizedBox(width: 6),
                Text('Connected people',
                    style: TextStyle(color: KaiColors.verified, fontSize: 12)),
              ]),
            )
          : _loading
              ? const Text('finding connections…',
                  style: TextStyle(color: KaiColors.muted, fontSize: 11))
              : (_conns == null || _conns!.isEmpty)
                  ? const Text('No connections found.',
                      style: TextStyle(color: KaiColors.muted, fontSize: 11))
                  : Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          '${_conns!.length} connected — associates to observe, not confirmed',
                          style: const TextStyle(
                              color: KaiColors.verified, fontSize: 10, letterSpacing: 0.5),
                        ),
                        const SizedBox(height: 6),
                        ..._conns!.map(_row),
                      ],
                    ),
    );
  }

  Widget _row(Map<String, dynamic> c) {
    final names = (c['names'] as List?)?.cast<dynamic>() ?? const [];
    final title = names.isNotEmpty
        ? names.first.toString()
        : (c['page_title']?.toString() ?? (c['face_id']?.toString() ?? '').padRight(8).substring(0, 8));
    final reasons = (c['reasons'] as List?)?.cast<dynamic>() ?? const [];
    final crop = c['crop_url']?.toString();
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Row(
        children: [
          if (crop != null)
            ClipRRect(
              borderRadius: BorderRadius.circular(4),
              child: Image.network(
                ApiClient.instance.imageUrl(crop),
                headers: ApiClient.instance.imageHeaders,
                width: 32,
                height: 32,
                fit: BoxFit.cover,
                errorBuilder: (_, _, _) =>
                    Container(width: 32, height: 32, color: KaiColors.panel2),
              ),
            ),
          const SizedBox(width: 8),
          Expanded(
            child: Text(title,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(color: KaiColors.ink, fontSize: 12)),
          ),
          ...reasons.take(2).map((r) => Padding(
                padding: const EdgeInsets.only(left: 4),
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 1),
                  decoration: BoxDecoration(
                    border: Border.all(color: KaiColors.line),
                    borderRadius: BorderRadius.circular(3),
                  ),
                  child: Text(_reasonLabel(r.toString()),
                      style: const TextStyle(color: KaiColors.muted, fontSize: 9)),
                ),
              )),
        ],
      ),
    );
  }
}
