import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../models/search_result.dart';
import '../../services/api_client.dart';
import '../../theme/hacker_theme.dart';

/// Universal search — GET /search?q=... Detects the query type and searches the
/// local corpus (entities + evidence across all investigations).
class UniversalSearchScreen extends StatefulWidget {
  const UniversalSearchScreen({super.key, this.initialQuery});

  final String? initialQuery;

  @override
  State<UniversalSearchScreen> createState() => _UniversalSearchScreenState();
}

class _UniversalSearchScreenState extends State<UniversalSearchScreen> {
  late final TextEditingController _c =
      TextEditingController(text: widget.initialQuery ?? '');
  bool _loading = false;
  String? _error;
  SearchResult? _result;

  @override
  void initState() {
    super.initState();
    if ((widget.initialQuery ?? '').trim().isNotEmpty) {
      WidgetsBinding.instance.addPostFrameCallback((_) => _run());
    }
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  Color _typeColor(String t) {
    switch (t) {
      case 'phone':
      case 'email':
      case 'username':
        return KaiColors.verified;
      case 'domain':
      case 'url':
        return KaiColors.warn;
      default:
        return KaiColors.muted;
    }
  }

  Future<void> _run() async {
    final q = _c.text.trim();
    if (q.isEmpty) return;
    FocusScope.of(context).unfocus();
    setState(() {
      _loading = true;
      _error = null;
      _result = null;
    });
    try {
      final r = await ApiClient.instance
          .getJson('/search?q=${Uri.encodeQueryComponent(q)}');
      if (r.statusCode != 200) {
        setState(() => _error = 'Search failed (HTTP ${r.statusCode}).');
      } else {
        final data = jsonDecode(r.body) as Map<String, dynamic>;
        setState(() => _result = SearchResult.fromJson(data));
      }
    } catch (_) {
      setState(() => _error = 'Cannot reach backend. Check settings.');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _open(String url) async {
    final uri = Uri.tryParse(url);
    if (uri != null && await canLaunchUrl(uri)) {
      await launchUrl(uri, mode: LaunchMode.externalApplication);
    }
  }

  @override
  Widget build(BuildContext context) {
    final res = _result;
    return Scaffold(
      appBar: AppBar(title: const Text('Universal Search')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          TextField(
            controller: _c,
            autofocus: (widget.initialQuery ?? '').isEmpty,
            textInputAction: TextInputAction.search,
            onSubmitted: (_) => _run(),
            decoration: InputDecoration(
              hintText: 'phone / email / username / domain / url',
              prefixIcon: const Icon(Icons.search, color: KaiColors.muted),
              suffixIcon: IconButton(
                icon: const Icon(Icons.arrow_forward, color: KaiColors.accent),
                onPressed: _loading ? null : _run,
              ),
            ),
          ),
          const SizedBox(height: 16),
          if (_loading)
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 24),
              child: Center(
                  child: Text('SEARCHING LOCAL CORPUS…',
                      style: TextStyle(color: KaiColors.muted, fontSize: 11))),
            ),
          if (_error != null)
            Text(_error!, style: const TextStyle(color: KaiColors.danger)),
          if (res != null && !_loading) ...[
            Wrap(
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                const Text('DETECTED: ',
                    style: TextStyle(color: KaiColors.muted, fontSize: 11)),
                Text(res.detectedType.toUpperCase(),
                    style: TextStyle(
                        color: _typeColor(res.detectedType),
                        fontSize: 11,
                        fontWeight: FontWeight.bold)),
                Text('  ·  normalized ${res.normalized}',
                    style: const TextStyle(color: KaiColors.muted, fontSize: 11)),
              ],
            ),
            const SizedBox(height: 16),
            _sectionLabel('ENTITIES (${res.entityMatches.length})'),
            if (res.entityMatches.isEmpty)
              _emptyBox('NO MATCH FOUND IN CURRENT INDEX')
            else
              ...res.entityMatches.map((e) => Container(
                    margin: const EdgeInsets.only(bottom: 8),
                    padding:
                        const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
                    decoration: _rowDecoration(),
                    child: Row(
                      children: [
                        Expanded(
                            child: Text(e.value,
                                style: const TextStyle(
                                    color: KaiColors.ink, fontSize: 13))),
                        Text(e.type.toUpperCase(),
                            style: const TextStyle(
                                color: KaiColors.muted, fontSize: 11)),
                      ],
                    ),
                  )),
            const SizedBox(height: 16),
            _sectionLabel('EVIDENCE (${res.evidenceMatches.length})'),
            if (res.evidenceMatches.isEmpty)
              _emptyBox('No source evidence in index.')
            else
              ...res.evidenceMatches.map((ev) => InkWell(
                    onTap: () => _open(ev.sourceUrl),
                    child: Container(
                      margin: const EdgeInsets.only(bottom: 8),
                      padding: const EdgeInsets.symmetric(
                          horizontal: 12, vertical: 10),
                      decoration: _rowDecoration(),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(ev.sourceUrl,
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: const TextStyle(
                                  color: KaiColors.verified, fontSize: 13)),
                          const SizedBox(height: 4),
                          Text(
                              '${ev.type}${ev.band != null ? ' · ${KaiColors.bandLabel(ev.band)}' : ''}',
                              style: const TextStyle(
                                  color: KaiColors.muted, fontSize: 11)),
                        ],
                      ),
                    ),
                  )),
          ],
        ],
      ),
    );
  }

  Widget _sectionLabel(String t) => Padding(
        padding: const EdgeInsets.only(bottom: 8),
        child: Text(t,
            style: const TextStyle(
                color: KaiColors.muted, fontSize: 11, letterSpacing: 1)),
      );

  BoxDecoration _rowDecoration() => BoxDecoration(
        color: KaiColors.panel,
        border: Border.all(color: KaiColors.line),
        borderRadius: BorderRadius.circular(8),
      );

  Widget _emptyBox(String t) => Container(
        width: double.infinity,
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(border: Border.all(color: KaiColors.line)),
        child: Text(t,
            style: const TextStyle(color: KaiColors.muted, fontSize: 12)),
      );
}
