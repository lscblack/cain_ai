import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../models/username_intel.dart';
import '../../services/api_client.dart';
import '../../theme/hacker_theme.dart';

/// Username intelligence — POST /intelligence/username {username}. Shows
/// per-platform public-profile presence + local matches.
class UsernameSearchScreen extends StatefulWidget {
  const UsernameSearchScreen({super.key, this.initialQuery});

  final String? initialQuery;

  @override
  State<UsernameSearchScreen> createState() => _UsernameSearchScreenState();
}

class _UsernameSearchScreenState extends State<UsernameSearchScreen> {
  late final TextEditingController _c =
      TextEditingController(text: widget.initialQuery ?? '');
  bool _loading = false;
  String? _error;
  UsernameIntelligence? _result;

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

  Color _statusColor(String s) {
    switch (s) {
      case 'found':
        return KaiColors.verified;
      case 'unknown':
        return KaiColors.warn;
      case 'error':
        return KaiColors.accent;
      default:
        return KaiColors.muted;
    }
  }

  Future<void> _run() async {
    final username = _c.text.trim();
    if (username.isEmpty) return;
    FocusScope.of(context).unfocus();
    setState(() {
      _loading = true;
      _error = null;
      _result = null;
    });
    try {
      final r = await ApiClient.instance
          .postJson('/intelligence/username', {'username': username});
      if (r.statusCode == 422) {
        setState(() => _error = 'Invalid username (2–40 chars).');
      } else if (r.statusCode != 200) {
        setState(() => _error = 'Check failed (HTTP ${r.statusCode}).');
      } else {
        final data = jsonDecode(r.body) as Map<String, dynamic>;
        setState(() => _result = UsernameIntelligence.fromJson(data));
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
      appBar: AppBar(title: const Text('Username Intelligence')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          TextField(
            controller: _c,
            textInputAction: TextInputAction.search,
            onSubmitted: (_) => _run(),
            decoration: const InputDecoration(hintText: 'handle (e.g. osint_guy)'),
          ),
          const SizedBox(height: 8),
          SizedBox(
            width: double.infinity,
            child: FilledButton(
              style: FilledButton.styleFrom(
                  backgroundColor: KaiColors.accent, foregroundColor: Colors.black),
              onPressed: _loading ? null : _run,
              child: Text(_loading ? 'CHECKING PUBLIC PROFILES…' : 'CHECK'),
            ),
          ),
          const SizedBox(height: 16),
          if (_error != null)
            Text(_error!, style: const TextStyle(color: KaiColors.danger)),
          if (res != null && !_loading) ...[
            Text(
                '${res.foundCount} reachable public profile(s) for ${res.username}',
                style: const TextStyle(color: KaiColors.muted, fontSize: 12)),
            const SizedBox(height: 12),
            ...res.results.map((h) => InkWell(
                  onTap: h.url.isEmpty ? null : () => _open(h.url),
                  child: Container(
                    margin: const EdgeInsets.only(bottom: 8),
                    padding: const EdgeInsets.symmetric(
                        horizontal: 12, vertical: 10),
                    decoration: BoxDecoration(
                      color: KaiColors.panel,
                      border: Border.all(color: KaiColors.line),
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: Row(
                      children: [
                        Container(
                          width: 8,
                          height: 8,
                          margin: const EdgeInsets.only(right: 10),
                          decoration: BoxDecoration(
                            color: _statusColor(h.status),
                            shape: BoxShape.circle,
                          ),
                        ),
                        Expanded(
                            child: Text(h.name.isNotEmpty ? h.name : h.platform,
                                style: const TextStyle(
                                    color: KaiColors.ink, fontSize: 13))),
                        Text(h.status.replaceAll('_', ' ').toUpperCase(),
                            style: TextStyle(
                                color: _statusColor(h.status), fontSize: 11)),
                        const SizedBox(width: 6),
                        const Icon(Icons.open_in_new,
                            size: 13, color: KaiColors.muted),
                      ],
                    ),
                  ),
                )),
            if (res.localEntityMatches.isNotEmpty) ...[
              const SizedBox(height: 8),
              Text('LOCAL MATCHES (${res.localEntityMatches.length})',
                  style: const TextStyle(
                      color: KaiColors.muted, fontSize: 11, letterSpacing: 1)),
              const SizedBox(height: 8),
              ...res.localEntityMatches.map((m) => Container(
                    margin: const EdgeInsets.only(bottom: 8),
                    padding: const EdgeInsets.symmetric(
                        horizontal: 10, vertical: 8),
                    decoration:
                        BoxDecoration(border: Border.all(color: KaiColors.line)),
                    child: Row(
                      children: [
                        Expanded(
                            child: Text(m.value,
                                style: const TextStyle(
                                    color: KaiColors.ink, fontSize: 13))),
                        Text(m.type.toUpperCase(),
                            style: const TextStyle(
                                color: KaiColors.muted, fontSize: 11)),
                      ],
                    ),
                  )),
            ],
            if (res.note.isNotEmpty) ...[
              const SizedBox(height: 12),
              Text(res.note,
                  style: const TextStyle(color: KaiColors.warn, fontSize: 11)),
            ],
          ],
        ],
      ),
    );
  }
}
