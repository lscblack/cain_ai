import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../models/email_intel.dart';
import '../../services/api_client.dart';
import '../../theme/hacker_theme.dart';

/// Email intelligence — POST /intelligence/email {email, check_dns}. Shows
/// MX/SPF/DMARC signals, gravatar, derived usernames + local matches.
class EmailSearchScreen extends StatefulWidget {
  const EmailSearchScreen({super.key, this.initialQuery});

  final String? initialQuery;

  @override
  State<EmailSearchScreen> createState() => _EmailSearchScreenState();
}

class _EmailSearchScreenState extends State<EmailSearchScreen> {
  late final TextEditingController _email =
      TextEditingController(text: widget.initialQuery ?? '');
  bool _checkDns = true;
  bool _loading = false;
  String? _error;
  EmailIntelligence? _result;

  @override
  void initState() {
    super.initState();
    if ((widget.initialQuery ?? '').trim().isNotEmpty) {
      WidgetsBinding.instance.addPostFrameCallback((_) => _run());
    }
  }

  @override
  void dispose() {
    _email.dispose();
    super.dispose();
  }

  Future<void> _run() async {
    final email = _email.text.trim();
    if (email.isEmpty) return;
    FocusScope.of(context).unfocus();
    setState(() {
      _loading = true;
      _error = null;
      _result = null;
    });
    try {
      final r = await ApiClient.instance.postJson('/intelligence/email', {
        'email': email,
        'check_dns': _checkDns,
      });
      if (r.statusCode != 200) {
        setState(() => _error = 'Analysis failed (HTTP ${r.statusCode}).');
      } else {
        final data = jsonDecode(r.body) as Map<String, dynamic>;
        setState(() => _result = EmailIntelligence.fromJson(data));
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
    final a = res?.analysis;
    return Scaffold(
      appBar: AppBar(title: const Text('Email Intelligence')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          TextField(
            controller: _email,
            keyboardType: TextInputType.emailAddress,
            textInputAction: TextInputAction.search,
            onSubmitted: (_) => _run(),
            decoration: const InputDecoration(hintText: 'person@example.com'),
          ),
          const SizedBox(height: 8),
          Row(
            children: [
              Checkbox(
                value: _checkDns,
                onChanged: (v) => setState(() => _checkDns = v ?? true),
                side: const BorderSide(color: KaiColors.line),
              ),
              const Text('Check DNS (MX / SPF / DMARC)',
                  style: TextStyle(color: KaiColors.muted, fontSize: 12)),
              const Spacer(),
            ],
          ),
          const SizedBox(height: 4),
          SizedBox(
            width: double.infinity,
            child: FilledButton(
              style: FilledButton.styleFrom(
                  backgroundColor: KaiColors.accent, foregroundColor: Colors.black),
              onPressed: _loading ? null : _run,
              child: Text(_loading ? 'CHECKING SIGNALS…' : 'ANALYZE'),
            ),
          ),
          const SizedBox(height: 16),
          if (_error != null)
            Text(_error!, style: const TextStyle(color: KaiColors.danger)),
          if (a != null && !_loading) ...[
            _card(
              header: 'DIRECT SIGNALS',
              headerRight: a.validFormat ? 'VALID FORMAT' : 'INVALID FORMAT',
              headerRightColor:
                  a.validFormat ? KaiColors.verified : KaiColors.accent,
              child: a.validFormat
                  ? Column(
                      children: [
                        _kv('Local', a.local),
                        _kv('Domain', a.domain),
                        if (a.dnsChecked) ...[
                          _signal('MX', a.hasMx,
                              value: a.mxRecords.isNotEmpty
                                  ? a.mxRecords.first
                                  : null),
                          _signal('SPF', a.spf != null && a.spf!.isNotEmpty),
                          _signal(
                              'DMARC', a.dmarc != null && a.dmarc!.isNotEmpty),
                        ] else
                          const Padding(
                            padding: EdgeInsets.symmetric(vertical: 8),
                            child: Text('DNS not checked',
                                style: TextStyle(
                                    color: KaiColors.muted, fontSize: 12)),
                          ),
                        if (a.derivedUsernames.isNotEmpty) ...[
                          const SizedBox(height: 10),
                          _chipsLabel('DERIVED USERNAMES (INFERRED)',
                              a.derivedUsernames),
                        ],
                        if (a.gravatarUrl != null) ...[
                          const SizedBox(height: 10),
                          InkWell(
                            onTap: () => _open(a.gravatarUrl!),
                            child: const Text('Gravatar candidate ↗',
                                style: TextStyle(
                                    color: KaiColors.verified, fontSize: 12)),
                          ),
                        ],
                        if (a.notes.isNotEmpty) ...[
                          const SizedBox(height: 10),
                          ...a.notes.map((n) => Padding(
                                padding: const EdgeInsets.only(bottom: 4),
                                child: Text('· $n',
                                    style: const TextStyle(
                                        color: KaiColors.muted, fontSize: 11)),
                              )),
                        ],
                      ],
                    )
                  : const Text('Address is not a valid email format.',
                      style: TextStyle(color: KaiColors.muted, fontSize: 13)),
            ),
            const SizedBox(height: 12),
            _card(
              header: 'LOCAL MATCHES (${res!.localEntityMatches.length})',
              child: res.localEntityMatches.isEmpty
                  ? const Text('NO MATCH FOUND IN CURRENT INDEX',
                      style: TextStyle(color: KaiColors.muted, fontSize: 12))
                  : Column(
                      children: res.localEntityMatches
                          .map((m) => _matchRow(m.value, m.type))
                          .toList(),
                    ),
            ),
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

  Widget _card({
    required String header,
    String? headerRight,
    Color? headerRightColor,
    required Widget child,
  }) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: KaiColors.panel,
        border: Border.all(color: KaiColors.line),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(header,
                  style: const TextStyle(
                      color: KaiColors.muted, fontSize: 11, letterSpacing: 1)),
              if (headerRight != null)
                Text(headerRight,
                    style: TextStyle(
                        color: headerRightColor ?? KaiColors.muted,
                        fontSize: 11,
                        fontWeight: FontWeight.bold)),
            ],
          ),
          const SizedBox(height: 10),
          child,
        ],
      ),
    );
  }

  Widget _kv(String label, String? value) => Container(
        decoration: const BoxDecoration(
            border: Border(bottom: BorderSide(color: KaiColors.line))),
        padding: const EdgeInsets.symmetric(vertical: 7),
        child: Row(
          children: [
            Expanded(
                child: Text(label.toUpperCase(),
                    style: const TextStyle(
                        color: KaiColors.muted, fontSize: 11))),
            Flexible(
              child: Text(value ?? '—',
                  textAlign: TextAlign.right,
                  style: const TextStyle(color: KaiColors.ink, fontSize: 13)),
            ),
          ],
        ),
      );

  Widget _signal(String label, bool? present, {String? value}) {
    final color = present == true
        ? KaiColors.verified
        : present == false
            ? KaiColors.accent
            : KaiColors.muted;
    return Container(
      decoration: const BoxDecoration(
          border: Border(bottom: BorderSide(color: KaiColors.line))),
      padding: const EdgeInsets.symmetric(vertical: 7),
      child: Row(
        children: [
          Expanded(
              child: Text(label.toUpperCase(),
                  style: const TextStyle(color: KaiColors.muted, fontSize: 11))),
          if (value != null)
            Flexible(
              child: Text(value,
                  textAlign: TextAlign.right,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(color: KaiColors.muted, fontSize: 11)),
            ),
          const SizedBox(width: 8),
          Icon(present == true ? Icons.check_circle : Icons.cancel,
              size: 16, color: color),
        ],
      ),
    );
  }

  Widget _chipsLabel(String label, List<String> values) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label,
              style: const TextStyle(color: KaiColors.muted, fontSize: 11)),
          const SizedBox(height: 6),
          Wrap(
            spacing: 6,
            runSpacing: 6,
            children: values
                .map((v) => Container(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 8, vertical: 3),
                      decoration: BoxDecoration(
                          border: Border.all(color: KaiColors.line),
                          borderRadius: BorderRadius.circular(4)),
                      child: Text(v,
                          style: const TextStyle(
                              color: KaiColors.ink, fontSize: 12)),
                    ))
                .toList(),
          ),
        ],
      );

  Widget _matchRow(String value, String type) => Container(
        margin: const EdgeInsets.only(bottom: 8),
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
        decoration: BoxDecoration(border: Border.all(color: KaiColors.line)),
        child: Row(
          children: [
            Expanded(
                child: Text(value,
                    style:
                        const TextStyle(color: KaiColors.ink, fontSize: 13))),
            Text(type.toUpperCase(),
                style: const TextStyle(color: KaiColors.muted, fontSize: 11)),
          ],
        ),
      );
}
