import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';

import '../services/api_client.dart';
import '../theme/hacker_theme.dart';

/// Animated strip of shifting indexed-face crops shown while a search runs —
/// the "scanning the index" hacker motif from the web UI.
class ScanningStrip extends StatefulWidget {
  final String label;
  const ScanningStrip({super.key, this.label = 'SCANNING LOCAL INDEX…'});

  @override
  State<ScanningStrip> createState() => _ScanningStripState();
}

class _ScanningStripState extends State<ScanningStrip> {
  List<String> _crops = [];
  int _tick = 0;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _loadCrops();
    _timer = Timer.periodic(const Duration(milliseconds: 160), (_) {
      if (mounted) setState(() => _tick++);
    });
  }

  Future<void> _loadCrops() async {
    try {
      final r =
          await ApiClient.instance.getJson('/intelligence/face/index-sample?limit=48');
      if (r.statusCode == 200) {
        final samples = (jsonDecode(r.body)['samples'] as List?) ?? [];
        final urls = samples
            .map((s) => (s as Map)['crop_url']?.toString())
            .whereType<String>()
            .toList();
        if (mounted) setState(() => _crops = urls);
      }
    } catch (_) {}
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    const n = 6;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Container(
              width: 8,
              height: 8,
              decoration: const BoxDecoration(
                  color: KaiColors.warn, shape: BoxShape.circle),
            ),
            const SizedBox(width: 6),
            Text(widget.label,
                style: const TextStyle(
                    color: KaiColors.warn, fontSize: 11, letterSpacing: 1)),
          ],
        ),
        const SizedBox(height: 8),
        SizedBox(
          height: 44,
          child: _crops.isEmpty
              ? const Text('comparing embeddings…',
                  style: TextStyle(color: KaiColors.muted, fontSize: 11))
              : Row(
                  children: List.generate(n, (i) {
                    final idx = (_tick + i) % _crops.length;
                    final opacity = 0.35 + 0.65 * ((i + _tick) % 3) / 2;
                    return Padding(
                      padding: const EdgeInsets.only(right: 6),
                      child: AnimatedOpacity(
                        duration: const Duration(milliseconds: 300),
                        opacity: opacity.clamp(0.3, 1.0),
                        child: ClipRRect(
                          borderRadius: BorderRadius.circular(4),
                          child: Image.network(
                            ApiClient.instance.imageUrl(_crops[idx]),
                            headers: ApiClient.instance.imageHeaders,
                            width: 44,
                            height: 44,
                            fit: BoxFit.cover,
                            errorBuilder: (_, _, _) => Container(
                                width: 44, height: 44, color: KaiColors.panel2),
                          ),
                        ),
                      ),
                    );
                  }),
                ),
        ),
      ],
    );
  }
}
