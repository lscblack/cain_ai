import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../models/person_group.dart';
import '../services/api_client.dart';
import '../theme/hacker_theme.dart';

/// Cyan HUD accent (mirrors the web `--kai-hud`).
const Color _hud = Color(0xFF22D3EE);

/// Mobile grouped "HUD" subject view for face search.
///
/// Mirrors the web [FaceResultsHUD] but laid out vertically for a phone:
///   1. a horizontal subject selector (crop · name · ×N · similarity%)
///   2. an appearance viewer (big square crop, ◀ ▶, filmstrip, source label)
///   3. a dossier (name, demographics, stat bars, attributes, what sources
///      say, AI bio, connected people).
///
/// Every match is a LEAD — the copy stays hedged ("potential match"), never a
/// confirmed identity.
class PersonHud extends StatefulWidget {
  final List<Person> people;
  const PersonHud({super.key, required this.people});

  @override
  State<PersonHud> createState() => _PersonHudState();
}

class _PersonHudState extends State<PersonHud> {
  int _sel = 0;
  int _appIdx = 0;

  Person get _person => widget.people[_sel];

  int get _maxAppearances => widget.people
      .map((p) => p.appearanceCount)
      .fold(1, (a, b) => a > b ? a : b);

  void _select(int i) {
    setState(() {
      _sel = i;
      _appIdx = 0;
    });
  }

  void _stepApp(int delta) {
    final n = _person.appearances.length;
    if (n == 0) return;
    setState(() => _appIdx = (_appIdx + delta + n) % n);
  }

  @override
  Widget build(BuildContext context) {
    final people = widget.people;
    final person = _person;
    final color = KaiColors.band(person.band);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          '${people.length} SUBJECT${people.length == 1 ? '' : 'S'} — leads to observe, not confirmed identity',
          style: const TextStyle(color: _hud, fontSize: 11, letterSpacing: 0.5),
        ),
        const SizedBox(height: 10),

        // 1 — subject selector
        _SubjectSelector(
          people: people,
          selected: _sel,
          onSelect: _select,
        ),
        const SizedBox(height: 14),

        // 2 + 3 — appearance viewer + dossier, cross-fading on subject switch
        AnimatedSwitcher(
          duration: const Duration(milliseconds: 320),
          switchInCurve: Curves.easeOut,
          transitionBuilder: (child, anim) => FadeTransition(
            opacity: anim,
            child: SizeTransition(
              sizeFactor:
                  CurvedAnimation(parent: anim, curve: Curves.easeOut),
              axisAlignment: -1,
              child: child,
            ),
          ),
          child: Column(
            key: ValueKey(person.personId),
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _AppearanceViewer(
                person: person,
                index: _person.appearances.isEmpty
                    ? 0
                    : _appIdx.clamp(0, _person.appearances.length - 1),
                onStep: _stepApp,
                onJump: (i) => setState(() => _appIdx = i),
              ),
              const SizedBox(height: 14),
              _Dossier(
                person: person,
                maxAppearances: _maxAppearances,
                bandColor: color,
              ),
            ],
          ),
        ),
      ],
    );
  }
}

// --------------------------------------------------------------------------
// Authenticated crop image (mobile equivalent of the web <AuthImg>).
// --------------------------------------------------------------------------
class _AuthImg extends StatelessWidget {
  final String? path;
  const _AuthImg({required this.path});

  @override
  Widget build(BuildContext context) {
    final p = path;
    if (p == null || p.isEmpty) return const _NoFace();
    return Image.network(
      ApiClient.instance.imageUrl(p),
      headers: ApiClient.instance.imageHeaders,
      fit: BoxFit.cover,
      errorBuilder: (_, _, _) => const _NoFace(),
    );
  }
}

class _NoFace extends StatelessWidget {
  const _NoFace();
  @override
  Widget build(BuildContext context) => Container(
        color: KaiColors.panel2,
        alignment: Alignment.center,
        child: const Icon(Icons.person, color: KaiColors.muted, size: 28),
      );
}

// --------------------------------------------------------------------------
// 1 — Subject selector: horizontal scrollable chips.
// --------------------------------------------------------------------------
class _SubjectSelector extends StatelessWidget {
  final List<Person> people;
  final int selected;
  final ValueChanged<int> onSelect;
  const _SubjectSelector({
    required this.people,
    required this.selected,
    required this.onSelect,
  });

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 92,
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        itemCount: people.length,
        separatorBuilder: (_, _) => const SizedBox(width: 8),
        itemBuilder: (_, i) {
          final p = people[i];
          final active = i == selected;
          final band = KaiColors.band(p.band);
          return InkWell(
            onTap: () => onSelect(i),
            borderRadius: BorderRadius.circular(8),
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 240),
              curve: Curves.easeOut,
              width: 128,
              padding: const EdgeInsets.all(6),
              decoration: BoxDecoration(
                color: active ? _hud.withValues(alpha: 0.10) : KaiColors.panel,
                border: Border.all(color: active ? _hud : KaiColors.line),
                borderRadius: BorderRadius.circular(8),
                boxShadow: active
                    ? [BoxShadow(color: _hud.withValues(alpha: 0.35), blurRadius: 14)]
                    : const [],
              ),
              child: Row(
                children: [
                  ClipRRect(
                    borderRadius: BorderRadius.circular(5),
                    child: Container(
                      width: 42,
                      height: 42,
                      decoration: BoxDecoration(border: Border.all(color: band)),
                      child: _AuthImg(path: p.cropUrl),
                    ),
                  ),
                  const SizedBox(width: 6),
                  Expanded(
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          p.displayName,
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                          style: TextStyle(
                            fontSize: 11,
                            height: 1.15,
                            fontWeight: FontWeight.w600,
                            color: active ? _hud : KaiColors.ink,
                          ),
                        ),
                        const SizedBox(height: 2),
                        Text(
                          '${_pct(p.similarityPct)} · ×${p.appearanceCount}',
                          style: const TextStyle(
                              color: KaiColors.muted, fontSize: 10),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          );
        },
      ),
    );
  }
}

// --------------------------------------------------------------------------
// 2 — Appearance viewer.
// --------------------------------------------------------------------------
class _AppearanceViewer extends StatelessWidget {
  final Person person;
  final int index;
  final ValueChanged<int> onStep;
  final ValueChanged<int> onJump;
  const _AppearanceViewer({
    required this.person,
    required this.index,
    required this.onStep,
    required this.onJump,
  });

  @override
  Widget build(BuildContext context) {
    final apps = person.appearances;
    final n = apps.length;
    final Appearance? app = n > 0 ? apps[index] : null;

    return Container(
      decoration: BoxDecoration(
        color: KaiColors.panel,
        border: Border.all(color: KaiColors.line),
        borderRadius: BorderRadius.circular(10),
      ),
      padding: const EdgeInsets.all(10),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '◢ APPEARANCE ${n == 0 ? 0 : index + 1}/$n',
            style: const TextStyle(
                color: _hud, fontSize: 11, letterSpacing: 1),
          ),
          const SizedBox(height: 8),
          AspectRatio(
            aspectRatio: 1,
            child: ClipRRect(
              borderRadius: BorderRadius.circular(8),
              child: Container(
                decoration:
                    BoxDecoration(border: Border.all(color: _hud.withValues(alpha: 0.5))),
                child: Stack(
                  fit: StackFit.expand,
                  children: [
                    _AuthImg(path: app?.cropUrl ?? app?.imageUrl),
                    if (n > 1) ...[
                      _navButton(Alignment.centerLeft, Icons.chevron_left,
                          () => onStep(-1)),
                      _navButton(Alignment.centerRight, Icons.chevron_right,
                          () => onStep(1)),
                    ],
                    // source label overlay
                    Positioned(
                      left: 0,
                      right: 0,
                      bottom: 0,
                      child: Container(
                        padding: const EdgeInsets.fromLTRB(8, 16, 8, 8),
                        decoration: const BoxDecoration(
                          gradient: LinearGradient(
                            begin: Alignment.bottomCenter,
                            end: Alignment.topCenter,
                            colors: [Colors.black87, Colors.transparent],
                          ),
                        ),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Text(
                              app?.label ?? 'no appearances',
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: const TextStyle(
                                  color: _hud,
                                  fontSize: 12,
                                  fontWeight: FontWeight.w600),
                            ),
                            Text(
                              '${app?.sourceDomain ?? '—'} · ${_pct(app?.similarityPct)}',
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: const TextStyle(
                                  color: KaiColors.muted, fontSize: 10),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
          if ((app?.caption?.isNotEmpty ?? false) ||
              (app?.context?.isNotEmpty ?? false)) ...[
            const SizedBox(height: 8),
            Text(
              (app!.caption?.isNotEmpty ?? false)
                  ? app.caption!
                  : app.context!,
              maxLines: 4,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(
                  color: KaiColors.muted, fontSize: 11, height: 1.4),
            ),
          ],
          // filmstrip
          if (n > 1) ...[
            const SizedBox(height: 10),
            SizedBox(
              height: 52,
              child: ListView.separated(
                scrollDirection: Axis.horizontal,
                itemCount: n,
                separatorBuilder: (_, _) => const SizedBox(width: 6),
                itemBuilder: (_, i) {
                  final active = i == index;
                  return InkWell(
                    onTap: () => onJump(i),
                    child: ClipRRect(
                      borderRadius: BorderRadius.circular(5),
                      child: Container(
                        width: 52,
                        height: 52,
                        decoration: BoxDecoration(
                          border: Border.all(
                              color: active ? _hud : KaiColors.line,
                              width: active ? 2 : 1),
                        ),
                        child: _AuthImg(path: apps[i].cropUrl),
                      ),
                    ),
                  );
                },
              ),
            ),
          ],
          if (app?.sourceUrl != null && app!.sourceUrl!.isNotEmpty) ...[
            const SizedBox(height: 10),
            OutlinedButton.icon(
              icon: const Icon(Icons.open_in_new, size: 14),
              label: const Text('OPEN SOURCE'),
              style: OutlinedButton.styleFrom(
                foregroundColor: KaiColors.verified,
                side: const BorderSide(color: KaiColors.line),
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
              ),
              onPressed: () => _open(app.sourceUrl!),
            ),
          ],
        ],
      ),
    );
  }

  Widget _navButton(Alignment align, IconData icon, VoidCallback onTap) {
    return Align(
      alignment: align,
      child: Padding(
        padding: const EdgeInsets.all(4),
        child: Material(
          color: Colors.black54,
          shape: const CircleBorder(),
          child: InkWell(
            customBorder: const CircleBorder(),
            onTap: onTap,
            child: Padding(
              padding: const EdgeInsets.all(4),
              child: Icon(icon, color: _hud, size: 24),
            ),
          ),
        ),
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

// --------------------------------------------------------------------------
// 3 — Dossier (per-subject; holds lazy bio + connections state).
// --------------------------------------------------------------------------
class _Dossier extends StatefulWidget {
  final Person person;
  final int maxAppearances;
  final Color bandColor;
  const _Dossier({
    super.key,
    required this.person,
    required this.maxAppearances,
    required this.bandColor,
  });

  @override
  State<_Dossier> createState() => _DossierState();
}

class _DossierState extends State<_Dossier> {
  // bio
  bool _bioRequested = false;
  bool _bioLoading = false;
  String? _bioText;
  String? _bioModel;

  // connections
  bool _connOpen = false;
  bool _connLoading = false;
  List<Map<String, dynamic>>? _conns;

  Person get p => widget.person;

  int _bandFill(String? b) {
    switch (b) {
      case 'potential_match':
        return 92;
      case 'strong_similarity':
        return 66;
      case 'possible_association':
        return 40;
      default:
        return 15;
    }
  }

  Future<void> _analyzeBio() async {
    setState(() {
      _bioRequested = true;
      _bioLoading = true;
    });
    try {
      final r = await ApiClient.instance.postJson('/intelligence/face/bio', {
        'name': p.name,
        'names': p.names,
        'titles': p.titles,
        'orgs': p.orgs,
        'locations': p.locations,
        'captions': p.appearances
            .map((a) => a.caption)
            .whereType<String>()
            .where((s) => s.isNotEmpty)
            .toList(),
        'contexts': p.contexts,
        'sources': p.appearances
            .map((a) => a.sourceUrl)
            .whereType<String>()
            .where((s) => s.isNotEmpty)
            .toList(),
        'age': p.age,
        'sex': p.sex,
      });
      if (r.statusCode == 200) {
        final data = jsonDecode(r.body) as Map<String, dynamic>;
        setState(() {
          _bioText = (data['bio'] ?? '').toString();
          _bioModel = data['model'] as String?;
        });
      } else {
        setState(() => _bioText = 'Bio analysis unavailable.');
      }
    } catch (_) {
      setState(() => _bioText = 'Bio analysis unavailable.');
    } finally {
      if (mounted) setState(() => _bioLoading = false);
    }
  }

  Future<void> _loadConnections() async {
    setState(() {
      _connOpen = true;
      _connLoading = true;
    });
    try {
      final r = await ApiClient.instance
          .getJson('/intelligence/face/${p.personId}/connections');
      if (r.statusCode == 200) {
        final list = (jsonDecode(r.body)['connections'] as List? ?? const [])
            .whereType<Map>()
            .map((e) => e.cast<String, dynamic>())
            .toList();
        setState(() => _conns = list);
      } else {
        setState(() => _conns = const []);
      }
    } catch (_) {
      setState(() => _conns = const []);
    } finally {
      if (mounted) setState(() => _connLoading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final demographics = [
      p.sex,
      (p.age ?? 0) > 0 ? '~${p.age}y' : null,
    ].whereType<String>().where((s) => s.isNotEmpty).join(' · ');

    return Container(
      width: double.infinity,
      decoration: BoxDecoration(
        color: KaiColors.panel,
        border: Border.all(color: KaiColors.line),
        borderRadius: BorderRadius.circular(10),
      ),
      padding: const EdgeInsets.all(14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // name + band
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      p.displayName.toUpperCase(),
                      style: const TextStyle(
                        color: _hud,
                        fontSize: 18,
                        fontWeight: FontWeight.bold,
                        letterSpacing: 0.5,
                        shadows: [
                          Shadow(color: _hud, blurRadius: 12),
                        ],
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      demographics.isEmpty ? 'demographics n/a' : demographics,
                      style:
                          const TextStyle(color: KaiColors.muted, fontSize: 11),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 8),
              Text(
                KaiColors.bandLabel(p.band),
                style: TextStyle(
                    color: widget.bandColor,
                    fontSize: 11,
                    letterSpacing: 0.5),
              ),
            ],
          ),
          const SizedBox(height: 14),

          // stat bars
          _StatBar(
            label: 'MATCH',
            pct: p.similarityPct ?? 0,
            value: _pct(p.similarityPct),
          ),
          const SizedBox(height: 8),
          _StatBar(
            label: 'FOOTPRINT',
            pct: p.appearanceCount /
                (widget.maxAppearances == 0 ? 1 : widget.maxAppearances) *
                100,
            value:
                '${p.appearanceCount} place${p.appearanceCount == 1 ? '' : 's'}',
          ),
          const SizedBox(height: 8),
          _StatBar(
            label: 'CONFIDENCE',
            pct: _bandFill(p.band).toDouble(),
            value: KaiColors.bandLabel(p.band).split(' ').first,
          ),
          const SizedBox(height: 14),

          // attributes
          _Attr(
            icon: Icons.work_outline,
            label: 'ROLE',
            values: [...p.titles.take(2), ...p.orgs.take(2)],
          ),
          _Attr(icon: Icons.place_outlined, label: 'LOCATION', values: p.locations),
          _Attr(
            icon: Icons.badge_outlined,
            label: 'ALIASES',
            values: p.names.skip(1).take(5).toList(),
          ),
          _Attr(icon: Icons.alternate_email, label: 'EMAILS', values: p.emails),
          _Attr(icon: Icons.phone_outlined, label: 'PHONES', values: p.phones),
          _Attr(icon: Icons.person_outline, label: 'SOCIAL', values: p.usernames),

          // what sources say
          if (p.contexts.isNotEmpty) ...[
            _divider(),
            const Text('WHAT SOURCES SAY',
                style: TextStyle(color: _hud, fontSize: 10, letterSpacing: 1)),
            const SizedBox(height: 6),
            ...p.contexts.map((c) => Padding(
                  padding: const EdgeInsets.only(bottom: 6),
                  child: Text(c,
                      style: const TextStyle(
                          color: KaiColors.muted, fontSize: 11, height: 1.4)),
                )),
          ],

          // AI bio
          _divider(),
          if (!_bioRequested)
            _linkButton(
              icon: Icons.auto_awesome,
              label: 'ANALYZE BIO',
              color: _hud,
              onTap: _analyzeBio,
            )
          else if (_bioLoading)
            const Text('analyzing…',
                style: TextStyle(color: KaiColors.muted, fontSize: 11))
          else
            Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('BIO${_bioModel != null ? ' · $_bioModel' : ' · composed'}',
                    style: const TextStyle(
                        color: _hud, fontSize: 10, letterSpacing: 1)),
                const SizedBox(height: 4),
                Text(_bioText ?? '',
                    style: const TextStyle(
                        color: KaiColors.ink, fontSize: 13, height: 1.45)),
              ],
            ),

          // connected people
          _divider(),
          if (!_connOpen)
            _linkButton(
              icon: Icons.groups_outlined,
              label: 'CONNECTED PEOPLE',
              color: KaiColors.verified,
              onTap: _loadConnections,
            )
          else if (_connLoading)
            const Text('finding connections…',
                style: TextStyle(color: KaiColors.muted, fontSize: 11))
          else if (_conns == null || _conns!.isEmpty)
            const Text('No connections found.',
                style: TextStyle(color: KaiColors.muted, fontSize: 11))
          else
            Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  '${_conns!.length} connected — associates to observe, not confirmed',
                  style: const TextStyle(
                      color: KaiColors.verified,
                      fontSize: 10,
                      letterSpacing: 0.5),
                ),
                const SizedBox(height: 6),
                ..._conns!.map(_connRow),
              ],
            ),
        ],
      ),
    );
  }

  Widget _divider() => const Padding(
        padding: EdgeInsets.symmetric(vertical: 12),
        child: Divider(color: KaiColors.line, height: 1),
      );

  Widget _linkButton({
    required IconData icon,
    required String label,
    required Color color,
    required VoidCallback onTap,
  }) {
    return InkWell(
      onTap: onTap,
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 15, color: color),
          const SizedBox(width: 6),
          Text(label,
              style: TextStyle(color: color, fontSize: 12, letterSpacing: 0.5)),
        ],
      ),
    );
  }

  Widget _connRow(Map<String, dynamic> c) {
    final names = (c['names'] as List?)?.cast<dynamic>() ?? const [];
    final fid = (c['face_id']?.toString() ?? '');
    final title = names.isNotEmpty
        ? names.first.toString()
        : (c['page_title']?.toString() ??
            (fid.length >= 8 ? fid.substring(0, 8) : fid));
    final reasons = (c['reasons'] as List?)?.cast<dynamic>() ?? const [];
    final crop = c['crop_url']?.toString();
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Row(
        children: [
          ClipRRect(
            borderRadius: BorderRadius.circular(4),
            child: SizedBox(
              width: 30,
              height: 30,
              child: _AuthImg(path: crop),
            ),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Text(title,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(color: KaiColors.ink, fontSize: 12)),
          ),
          if (reasons.isNotEmpty)
            Container(
              margin: const EdgeInsets.only(left: 4),
              padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 1),
              decoration: BoxDecoration(
                border: Border.all(color: KaiColors.line),
                borderRadius: BorderRadius.circular(3),
              ),
              child: Text(_reasonLabel(reasons.first.toString()),
                  style: const TextStyle(color: KaiColors.muted, fontSize: 9)),
            ),
        ],
      ),
    );
  }

  String _reasonLabel(String r) {
    if (r == 'co_located') return 'same page';
    if (r.startsWith('shares:')) return 'shares ${r.substring(7)}';
    return r;
  }
}

class _StatBar extends StatelessWidget {
  final String label;
  final double pct;
  final String value;
  const _StatBar({required this.label, required this.pct, required this.value});

  @override
  Widget build(BuildContext context) {
    final clamped = pct.clamp(0, 100).toDouble();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Text(label,
                style: const TextStyle(
                    color: KaiColors.muted, fontSize: 10, letterSpacing: 1)),
            Text(value, style: const TextStyle(color: _hud, fontSize: 11)),
          ],
        ),
        const SizedBox(height: 4),
        ClipRRect(
          borderRadius: BorderRadius.circular(3),
          child: LinearProgressIndicator(
            value: clamped / 100,
            minHeight: 6,
            backgroundColor: KaiColors.panel2,
            valueColor: const AlwaysStoppedAnimation<Color>(_hud),
          ),
        ),
      ],
    );
  }
}

class _Attr extends StatelessWidget {
  final IconData icon;
  final String label;
  final List<String> values;
  const _Attr({required this.icon, required this.label, required this.values});

  @override
  Widget build(BuildContext context) {
    if (values.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, size: 14, color: _hud),
          const SizedBox(width: 8),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(label,
                    style: const TextStyle(
                        color: KaiColors.muted,
                        fontSize: 10,
                        letterSpacing: 1)),
                Wrap(
                  spacing: 12,
                  runSpacing: 2,
                  children: values
                      .map((v) => Text(v,
                          style: const TextStyle(
                              color: KaiColors.ink, fontSize: 13)))
                      .toList(),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

String _pct(double? v) => v == null ? '—' : '${v.round()}%';
