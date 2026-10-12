import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';

import '../models/report_match.dart';
import '../services/api_client.dart';
import '../theme/hacker_theme.dart';
import '../widgets/report_card.dart';
import '../widgets/scanning_strip.dart';

class FaceSearchScreen extends StatefulWidget {
  const FaceSearchScreen({super.key});

  @override
  State<FaceSearchScreen> createState() => _FaceSearchScreenState();
}

class _FaceSearchScreenState extends State<FaceSearchScreen> {
  final _picker = ImagePicker();
  Uint8List? _queryBytes;
  bool _loading = false;
  String? _error;
  List<ReportMatch>? _matches;

  Future<void> _pick(ImageSource source) async {
    try {
      final x = await _picker.pickImage(source: source, maxWidth: 1600, imageQuality: 90);
      if (x == null) return;
      final bytes = await x.readAsBytes();
      setState(() {
        _queryBytes = bytes;
        _matches = null;
        _error = null;
      });
      await _search();
    } catch (e) {
      setState(() => _error = 'Could not read image.');
    }
  }

  Future<void> _search() async {
    if (_queryBytes == null) return;
    setState(() {
      _loading = true;
      _error = null;
      _matches = null;
    });
    try {
      final r = await ApiClient.instance.postImage(
        '/intelligence/face/search',
        _queryBytes!,
        filename: 'query.jpg',
        fields: {'top_k': '12'},
      );
      if (r.statusCode == 503) {
        setState(() => _error = 'FACE ENGINE UNAVAILABLE on the server.');
      } else if (r.statusCode != 200) {
        setState(() => _error = 'Search failed (HTTP ${r.statusCode}).');
      } else {
        final data = jsonDecode(r.body);
        final list = (data['matches'] as List? ?? [])
            .map((m) => ReportMatch.fromJson(m as Map<String, dynamic>))
            .toList();
        setState(() => _matches = list);
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
      appBar: AppBar(title: const Text('Face Search')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                width: 110,
                height: 110,
                decoration: BoxDecoration(
                  color: KaiColors.panel,
                  border: Border.all(color: KaiColors.line),
                  borderRadius: BorderRadius.circular(8),
                ),
                clipBehavior: Clip.antiAlias,
                child: _queryBytes != null
                    ? Image.memory(_queryBytes!, fit: BoxFit.cover)
                    : const Icon(Icons.person_search, color: KaiColors.muted, size: 32),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text('QUERY FACE',
                        style: TextStyle(color: KaiColors.muted, fontSize: 11, letterSpacing: 1)),
                    const SizedBox(height: 8),
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
                    if (_queryBytes != null)
                      Padding(
                        padding: const EdgeInsets.only(top: 8),
                        child: SizedBox(
                          width: double.infinity,
                          child: FilledButton(
                            style: FilledButton.styleFrom(
                                backgroundColor: KaiColors.accent, foregroundColor: Colors.black),
                            onPressed: _loading ? null : _search,
                            child: Text(_loading ? 'SCANNING…' : 'SEARCH INDEX'),
                          ),
                        ),
                      ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 20),
          if (_error != null)
            Text(_error!, style: const TextStyle(color: KaiColors.danger)),
          if (_loading)
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 12),
              child: ScanningStrip(),
            ),
          if (_matches != null && !_loading) ...[
            if (_matches!.isEmpty)
              Container(
                padding: const EdgeInsets.all(24),
                alignment: Alignment.center,
                decoration: BoxDecoration(border: Border.all(color: KaiColors.line)),
                child: const Text('NO MATCH FOUND',
                    style: TextStyle(color: KaiColors.muted, fontWeight: FontWeight.bold)),
              )
            else ...[
              Padding(
                padding: const EdgeInsets.only(bottom: 10),
                child: Text(
                  '${_matches!.length} POTENTIAL MATCH${_matches!.length == 1 ? '' : 'ES'} — leads to observe, not confirmed identity',
                  style: const TextStyle(color: KaiColors.verified, fontSize: 11),
                ),
              ),
              ..._matches!.map((m) => ReportCard(m: m)),
            ],
          ],
        ],
      ),
    );
  }
}
