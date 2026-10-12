import 'dart:convert';
import 'dart:typed_data';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';

import '../models/report_match.dart';
import '../services/api_client.dart';
import '../theme/hacker_theme.dart';
import '../widgets/report_card.dart';
import '../widgets/scanning_strip.dart';

/// One distinct person detected across the sampled video frames, with their
/// ranked index matches. Mirrors a `people[]` entry from
/// `POST /intelligence/face/search/video`.
class VideoPerson {
  final int? age;
  final String? sex;
  final double? quality;
  final int framesSeen;
  final List<ReportMatch> matches;

  VideoPerson({
    this.age,
    this.sex,
    this.quality,
    this.framesSeen = 0,
    this.matches = const [],
  });

  factory VideoPerson.fromJson(Map<String, dynamic> j) => VideoPerson(
        age: (j['age'] as num?)?.toInt(),
        sex: j['sex'] as String?,
        quality: (j['quality'] as num?)?.toDouble(),
        framesSeen: (j['frames_seen'] as num?)?.toInt() ?? 0,
        matches: (j['matches'] as List? ?? const [])
            .map((m) => ReportMatch.fromJson(m as Map<String, dynamic>))
            .toList(),
      );
}

/// Pick a video file, upload it for frame-by-frame face search, and render the
/// distinct people found plus their potential index matches (leads, never a
/// confirmed identity).
class VideoSearchScreen extends StatefulWidget {
  const VideoSearchScreen({super.key});

  @override
  State<VideoSearchScreen> createState() => _VideoSearchScreenState();
}

class _VideoSearchScreenState extends State<VideoSearchScreen> {
  bool _loading = false;
  String? _error;
  String? _fileName;
  int? _framesSampled;
  int? _facesFound;
  List<VideoPerson>? _people;

  Future<void> _pickAndSearch() async {
    setState(() {
      _error = null;
    });
    PlatformFile? picked;
    try {
      picked = await FilePicker.pickFile(type: FileType.video);
    } catch (_) {
      setState(() => _error = 'Could not open the file picker.');
      return;
    }
    if (picked == null) return;

    final f = picked;
    Uint8List bytes;
    try {
      bytes = await f.readAsBytes();
    } catch (_) {
      setState(() => _error = 'Could not read the selected video.');
      return;
    }
    if (bytes.isEmpty) {
      setState(() => _error = 'Selected video is empty.');
      return;
    }

    setState(() {
      _fileName = f.name;
      _loading = true;
      _error = null;
      _people = null;
      _framesSampled = null;
      _facesFound = null;
    });

    try {
      final name = f.name.isNotEmpty ? f.name : 'clip.mp4';
      final ext = name.contains('.') ? name.split('.').last.toLowerCase() : 'mp4';
      final contentType = ext == 'webm'
          ? 'video/webm'
          : (ext == 'mov' || ext == 'qt')
              ? 'video/quicktime'
              : 'video/mp4';
      final r = await ApiClient.instance.postImage(
        '/intelligence/face/search/video',
        bytes,
        filename: name,
        contentType: contentType,
      );
      if (r.statusCode == 503) {
        setState(() => _error = 'FACE ENGINE UNAVAILABLE on the server.');
      } else if (r.statusCode == 413) {
        setState(() => _error = 'Video too large (max 50 MB).');
      } else if (r.statusCode == 415) {
        setState(() => _error = 'Unsupported video type (use mp4/webm/mov).');
      } else if (r.statusCode != 200) {
        setState(() => _error = 'Search failed (HTTP ${r.statusCode}).');
      } else {
        final data = jsonDecode(r.body) as Map<String, dynamic>;
        final people = (data['people'] as List? ?? const [])
            .map((p) => VideoPerson.fromJson(p as Map<String, dynamic>))
            .toList();
        setState(() {
          _framesSampled = (data['frames_sampled'] as num?)?.toInt() ?? 0;
          _facesFound = (data['faces_found'] as num?)?.toInt() ?? people.length;
          _people = people;
        });
      }
    } catch (e) {
      setState(() => _error = 'Cannot reach backend. Check settings.');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Video Face Search')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: KaiColors.panel,
              border: Border.all(color: KaiColors.line),
              borderRadius: BorderRadius.circular(8),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text('VIDEO CLIP',
                    style: TextStyle(
                        color: KaiColors.muted, fontSize: 11, letterSpacing: 1)),
                const SizedBox(height: 4),
                Text(
                  _fileName ?? 'Pick a short clip (mp4 / webm / mov, max 50 MB).',
                  style: const TextStyle(color: KaiColors.ink, fontSize: 13),
                ),
                const SizedBox(height: 10),
                SizedBox(
                  width: double.infinity,
                  child: FilledButton.icon(
                    style: FilledButton.styleFrom(
                        backgroundColor: KaiColors.accent,
                        foregroundColor: Colors.black),
                    icon: const Icon(Icons.video_library_outlined, size: 18),
                    label: Text(_loading ? 'SCANNING…' : 'PICK VIDEO & SCAN'),
                    onPressed: _loading ? null : _pickAndSearch,
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 16),
          if (_error != null)
            Text(_error!, style: const TextStyle(color: KaiColors.danger)),
          if (_loading) ...[
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 12),
              child: ScanningStrip(label: 'SAMPLING FRAMES & SCANNING INDEX…'),
            ),
            const Text(
              'Sampling frames at ~1 fps and matching each face. This can take '
              'a while for longer clips.',
              style: TextStyle(color: KaiColors.muted, fontSize: 11),
            ),
          ],
          if (_people != null && !_loading) ...[
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
              decoration: BoxDecoration(
                color: KaiColors.panel2,
                border: Border.all(color: KaiColors.line),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.spaceAround,
                children: [
                  _stat('FRAMES', '${_framesSampled ?? 0}'),
                  _stat('FACES', '${_facesFound ?? _people!.length}'),
                ],
              ),
            ),
            const SizedBox(height: 12),
            if (_people!.isEmpty)
              Container(
                padding: const EdgeInsets.all(24),
                alignment: Alignment.center,
                decoration: BoxDecoration(border: Border.all(color: KaiColors.line)),
                child: const Text('NO FACES DETECTED IN CLIP',
                    style: TextStyle(
                        color: KaiColors.muted, fontWeight: FontWeight.bold)),
              )
            else
              ..._people!.asMap().entries.map((e) => _personBlock(e.key, e.value)),
          ],
        ],
      ),
    );
  }

  Widget _stat(String label, String value) => Column(
        children: [
          Text(value,
              style: const TextStyle(
                  color: KaiColors.accent,
                  fontSize: 22,
                  fontWeight: FontWeight.bold)),
          Text(label,
              style: const TextStyle(
                  color: KaiColors.muted, fontSize: 10, letterSpacing: 1)),
        ],
      );

  Widget _personBlock(int index, VideoPerson p) {
    final demo = [
      p.sex,
      (p.age ?? 0) > 0 ? '~${p.age}y' : null,
    ].whereType<String>().join(' · ');
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Padding(
          padding: const EdgeInsets.only(top: 6, bottom: 6),
          child: Text(
            'PERSON ${index + 1}'
            '${demo.isNotEmpty ? ' · $demo' : ''}'
            ' · seen in ${p.framesSeen} frame${p.framesSeen == 1 ? '' : 's'}',
            style: const TextStyle(
                color: KaiColors.warn, fontSize: 11, letterSpacing: 0.5),
          ),
        ),
        if (p.matches.isEmpty)
          Padding(
            padding: const EdgeInsets.only(bottom: 12),
            child: Text(
              'No index match — face observed but not in the local index.',
              style: const TextStyle(color: KaiColors.muted, fontSize: 12),
            ),
          )
        else ...[
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: Text(
              '${p.matches.length} potential match${p.matches.length == 1 ? '' : 'es'} — leads to observe, not confirmed identity',
              style: const TextStyle(color: KaiColors.verified, fontSize: 11),
            ),
          ),
          ...p.matches.map((m) => ReportCard(m: m)),
        ],
      ],
    );
  }
}
