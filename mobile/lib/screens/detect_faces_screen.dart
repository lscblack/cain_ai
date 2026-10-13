import 'dart:convert';
import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'package:url_launcher/url_launcher.dart';

import '../models/detected_face.dart';
import '../models/person_group.dart';
import '../services/api_client.dart';
import '../theme/hacker_theme.dart';
import '../widgets/kai_anim.dart';
import '../widgets/scanning_strip.dart';

/// Multi-face "Detect Faces" screen.
///
/// Pick/capture a photo → one call to POST /intelligence/face/search with
/// all_faces=true (detect every face once, search each against the local
/// index) → draw numbered boxes over the uploaded image and, per face, show
/// its potential-match people as horizontally-scrollable image cards.
///
/// Every match is an investigative LEAD — wording stays hedged ("potential"),
/// never a confirmed identity.
class DetectFacesScreen extends StatefulWidget {
  const DetectFacesScreen({super.key});

  @override
  State<DetectFacesScreen> createState() => _DetectFacesScreenState();
}

class _DetectFacesScreenState extends State<DetectFacesScreen> {
  final _picker = ImagePicker();

  Uint8List? _bytes;
  ui.Image? _decoded; // intrinsic pixel size, to map bbox → display
  bool _loading = false;
  String? _error;
  String? _note;
  List<DetectedFace>? _faces;
  int _selected = 0;

  Future<void> _pick(ImageSource source) async {
    try {
      final x =
          await _picker.pickImage(source: source, maxWidth: 1600, imageQuality: 90);
      if (x == null) return;
      final bytes = await x.readAsBytes();
      final decoded = await decodeImageFromList(bytes);
      setState(() {
        _bytes = bytes;
        _decoded = decoded;
        _faces = null;
        _error = null;
        _note = null;
        _selected = 0;
      });
      await _detect();
    } catch (_) {
      setState(() => _error = 'Could not read image.');
    }
  }

  Future<void> _detect() async {
    if (_bytes == null) return;
    setState(() {
      _loading = true;
      _error = null;
      _faces = null;
    });
    try {
      final r = await ApiClient.instance.postImage(
        '/intelligence/face/search',
        _bytes!,
        filename: 'detect.jpg',
        fields: {'all_faces': 'true', 'top_k': '8'},
      );
      if (r.statusCode == 503) {
        setState(() => _error = 'FACE ENGINE UNAVAILABLE on the server.');
      } else if (r.statusCode != 200) {
        setState(() => _error = 'Detection failed (HTTP ${r.statusCode}).');
      } else {
        final data = jsonDecode(r.body) as Map<String, dynamic>;
        final faces = DetectedFace.listFromJson(data['faces']);
        faces.sort((a, b) => a.faceIndex.compareTo(b.faceIndex));
        setState(() {
          _faces = faces;
          _note = data['note'] as String?;
          _selected = 0;
        });
      }
    } catch (_) {
      setState(() => _error = 'Cannot reach backend. Check settings.');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final faces = _faces;
    return Scaffold(
      appBar: AppBar(
        title: const Text('Detect Faces'),
        bottom: const PreferredSize(
          preferredSize: Size.fromHeight(2),
          child: HeaderSweep(),
        ),
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          _pickerRow(),
          const SizedBox(height: 16),
          if (_bytes != null) _imageWithBoxes(),
          if (_error != null) ...[
            const SizedBox(height: 14),
            Text(_error!, style: const TextStyle(color: KaiColors.danger)),
          ],
          if (_loading) ...[
            const SizedBox(height: 16),
            const HudHeader('DETECTING & SCANNING'),
            const SizedBox(height: 10),
            const ScanningStrip(label: 'SCANNING EVERY FACE…'),
          ],
          if (faces != null && !_loading) ...[
            const SizedBox(height: 16),
            AppearFade(child: _results(faces)),
          ],
        ],
      ),
    );
  }

  // --- image picker row ----------------------------------------------------
  Widget _pickerRow() {
    return HudPanel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const HudHeader('SUBJECT IMAGE'),
          const SizedBox(height: 4),
          const Text(
            'Detect every face in one photo and scan each against the local index.',
            style: TextStyle(color: KaiColors.muted, fontSize: 11, height: 1.4),
          ),
          const SizedBox(height: 10),
          Row(children: [
            Expanded(
              child: OutlinedButton.icon(
                icon: const Icon(Icons.photo_library_outlined, size: 16),
                label: const Text('Gallery'),
                onPressed: _loading ? null : () => _pick(ImageSource.gallery),
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: OutlinedButton.icon(
                icon: const Icon(Icons.photo_camera_outlined, size: 16),
                label: const Text('Camera'),
                onPressed: _loading ? null : () => _pick(ImageSource.camera),
              ),
            ),
          ]),
          if (_bytes != null)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: SizedBox(
                width: double.infinity,
                child: FilledButton.icon(
                  style: FilledButton.styleFrom(
                      backgroundColor: KaiColors.hud,
                      foregroundColor: Colors.black),
                  icon: const Icon(Icons.center_focus_strong, size: 16),
                  onPressed: _loading ? null : _detect,
                  label: Text(_loading ? 'SCANNING…' : 'RE-DETECT FACES'),
                ),
              ),
            ),
        ],
      ),
    );
  }

  // --- uploaded image with numbered bounding boxes -------------------------
  Widget _imageWithBoxes() {
    final img = _decoded;
    final bytes = _bytes!;
    final aspect = (img != null && img.height > 0)
        ? img.width / img.height
        : 1.0;
    final faces = _faces ?? const [];

    return ClipRRect(
      borderRadius: BorderRadius.circular(8),
      child: AspectRatio(
        aspectRatio: aspect,
        child: LayoutBuilder(
          builder: (context, constraints) {
            final dispW = constraints.maxWidth;
            final dispH = constraints.maxHeight;
            final sx = (img != null && img.width > 0) ? dispW / img.width : 1.0;
            final sy =
                (img != null && img.height > 0) ? dispH / img.height : 1.0;
            return Stack(
              fit: StackFit.expand,
              children: [
                Image.memory(bytes, fit: BoxFit.cover),
                if (!_loading)
                  for (var i = 0; i < faces.length; i++)
                    _box(faces[i], i, sx, sy),
              ],
            );
          },
        ),
      ),
    );
  }

  Widget _box(DetectedFace f, int i, double sx, double sy) {
    final b = f.bbox;
    final left = b[0] * sx;
    final top = b[1] * sy;
    final w = (b[2] - b[0]) * sx;
    final h = (b[3] - b[1]) * sy;
    final active = i == _selected;
    final color = f.hasMatches ? KaiColors.hud : KaiColors.muted;
    return Positioned(
      left: left,
      top: top,
      width: w <= 0 ? 1 : w,
      height: h <= 0 ? 1 : h,
      child: GestureDetector(
        onTap: () => setState(() => _selected = i),
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 220),
          decoration: BoxDecoration(
            border: Border.all(color: color, width: active ? 2.5 : 1.5),
            borderRadius: BorderRadius.circular(3),
            boxShadow: active
                ? [BoxShadow(color: color.withValues(alpha: 0.6), blurRadius: 10)]
                : const [],
          ),
          child: Align(
            alignment: Alignment.topLeft,
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 1),
              color: color,
              child: Text(
                '${i + 1}',
                style: const TextStyle(
                    color: Colors.black,
                    fontSize: 10,
                    fontWeight: FontWeight.bold),
              ),
            ),
          ),
        ),
      ),
    );
  }

  // --- results -------------------------------------------------------------
  Widget _results(List<DetectedFace> faces) {
    if (faces.isEmpty) {
      return Container(
        padding: const EdgeInsets.all(24),
        alignment: Alignment.center,
        decoration: BoxDecoration(border: Border.all(color: KaiColors.line)),
        child: const Text('NO FACES DETECTED',
            style:
                TextStyle(color: KaiColors.muted, fontWeight: FontWeight.bold)),
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          '${faces.length} FACE${faces.length == 1 ? '' : 'S'} DETECTED — leads to observe, not confirmed identity',
          style: const TextStyle(
              color: KaiColors.hud, fontSize: 11, letterSpacing: 0.5),
        ),
        if (_note != null && _note!.trim().isNotEmpty) ...[
          const SizedBox(height: 4),
          Text(_note!,
              style: const TextStyle(color: KaiColors.muted, fontSize: 10)),
        ],
        const SizedBox(height: 12),
        for (var i = 0; i < faces.length; i++)
          RevealIn(
            index: i,
            child: Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: _FaceCard(
                face: faces[i],
                selected: i == _selected,
                onTap: () => setState(() => _selected = i),
              ),
            ),
          ),
      ],
    );
  }
}

// --------------------------------------------------------------------------
// Per-face HUD card: demographics/quality + horizontally scrollable matches.
// --------------------------------------------------------------------------
class _FaceCard extends StatelessWidget {
  final DetectedFace face;
  final bool selected;
  final VoidCallback onTap;
  const _FaceCard(
      {required this.face, required this.selected, required this.onTap});

  @override
  Widget build(BuildContext context) {
    final quality = face.quality;
    return GestureDetector(
      onTap: onTap,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 220),
        decoration: BoxDecoration(
          border: Border.all(
              color: selected ? KaiColors.hud : KaiColors.hudDim,
              width: selected ? 1.5 : 1),
          borderRadius: BorderRadius.circular(6),
          boxShadow: selected
              ? const [BoxShadow(color: Color(0x2222D3EE), blurRadius: 18)]
              : const [],
        ),
        child: HudPanel(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  _IndexBadge(index: face.faceIndex, hasMatches: face.hasMatches),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(face.label,
                            style: const TextStyle(
                                color: KaiColors.hud,
                                fontSize: 13,
                                fontWeight: FontWeight.bold,
                                letterSpacing: 1)),
                        Text(
                          [
                            face.demographics,
                            if (quality != null)
                              'q ${(quality * 100).round()}%',
                            '${face.matchCount} lead${face.matchCount == 1 ? '' : 's'}',
                          ].whereType<String>().join('  ·  '),
                          style: const TextStyle(
                              color: KaiColors.muted, fontSize: 10),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
              if (quality != null) ...[
                const SizedBox(height: 8),
                HudBar(quality.clamp(0.0, 1.0)),
              ],
              const SizedBox(height: 10),
              if (!face.hasMatches)
                Container(
                  width: double.infinity,
                  padding: const EdgeInsets.symmetric(vertical: 14),
                  alignment: Alignment.center,
                  decoration:
                      BoxDecoration(border: Border.all(color: KaiColors.line)),
                  child: const Text('NO MATCH IN INDEX',
                      style: TextStyle(color: KaiColors.muted, fontSize: 11)),
                )
              else
                SizedBox(
                  height: 214,
                  child: ListView.separated(
                    scrollDirection: Axis.horizontal,
                    itemCount: face.people.length,
                    separatorBuilder: (_, _) => const SizedBox(width: 10),
                    itemBuilder: (_, i) => _MatchCard(person: face.people[i]),
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }
}

class _IndexBadge extends StatelessWidget {
  final int index;
  final bool hasMatches;
  const _IndexBadge({required this.index, required this.hasMatches});

  @override
  Widget build(BuildContext context) {
    final color = hasMatches ? KaiColors.hud : KaiColors.muted;
    return Container(
      width: 28,
      height: 28,
      alignment: Alignment.center,
      decoration: BoxDecoration(
        border: Border.all(color: color),
        borderRadius: BorderRadius.circular(4),
        color: color.withValues(alpha: 0.12),
      ),
      child: Text('${index + 1}',
          style: TextStyle(
              color: color, fontWeight: FontWeight.bold, fontSize: 13)),
    );
  }
}

// --------------------------------------------------------------------------
// One potential-match person rendered as an image card.
// --------------------------------------------------------------------------
class _MatchCard extends StatelessWidget {
  final Person person;
  const _MatchCard({required this.person});

  String? get _sourceUrl {
    for (final a in person.appearances) {
      if (a.sourceUrl != null && a.sourceUrl!.isNotEmpty) return a.sourceUrl;
    }
    return null;
  }

  Future<void> _open() async {
    final url = _sourceUrl;
    if (url == null) return;
    final uri = Uri.tryParse(url);
    if (uri != null && await canLaunchUrl(uri)) {
      await launchUrl(uri, mode: LaunchMode.externalApplication);
    }
  }

  @override
  Widget build(BuildContext context) {
    final band = KaiColors.band(person.band);
    final src = _sourceUrl;
    return Container(
      width: 148,
      decoration: BoxDecoration(
        color: KaiColors.panel,
        border: Border.all(color: KaiColors.line),
        borderRadius: BorderRadius.circular(8),
      ),
      clipBehavior: Clip.antiAlias,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // crop + similarity overlay
          AspectRatio(
            aspectRatio: 1,
            child: Stack(
              fit: StackFit.expand,
              children: [
                _AuthImg(path: person.cropUrl),
                Positioned(
                  top: 6,
                  left: 6,
                  child: Container(
                    padding:
                        const EdgeInsets.symmetric(horizontal: 5, vertical: 2),
                    color: Colors.black.withValues(alpha: 0.65),
                    child: Text(
                      person.similarityPct == null
                          ? '—'
                          : '${person.similarityPct!.round()}%',
                      style: TextStyle(
                          color: band,
                          fontSize: 12,
                          fontWeight: FontWeight.bold),
                    ),
                  ),
                ),
                Positioned(
                  left: 0,
                  right: 0,
                  bottom: 0,
                  child: Container(
                    color: band.withValues(alpha: 0.18),
                    padding:
                        const EdgeInsets.symmetric(horizontal: 6, vertical: 3),
                    child: Text(
                      KaiColors.bandLabel(person.band),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(
                          color: band, fontSize: 9, letterSpacing: 0.5),
                    ),
                  ),
                ),
              ],
            ),
          ),
          Padding(
            padding: const EdgeInsets.all(8),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  person.displayName,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                      color: KaiColors.ink,
                      fontSize: 12,
                      height: 1.2,
                      fontWeight: FontWeight.w600),
                ),
                const SizedBox(height: 2),
                Text('×${person.appearanceCount} appearance${person.appearanceCount == 1 ? '' : 's'}',
                    style:
                        const TextStyle(color: KaiColors.muted, fontSize: 10)),
                const SizedBox(height: 4),
                if (src != null)
                  InkWell(
                    onTap: _open,
                    child: const Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(Icons.open_in_new,
                            size: 12, color: KaiColors.verified),
                        SizedBox(width: 4),
                        Text('SOURCE',
                            style: TextStyle(
                                color: KaiColors.verified,
                                fontSize: 10,
                                letterSpacing: 0.5)),
                      ],
                    ),
                  )
                else
                  const Text('no source link',
                      style: TextStyle(color: KaiColors.muted, fontSize: 10)),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

/// Authenticated crop image (mirror of the web <AuthImg>).
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
