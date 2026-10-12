import 'dart:convert';

import 'package:flutter/material.dart';

import '../../models/phone_intel.dart';
import '../../services/api_client.dart';
import '../../theme/hacker_theme.dart';

/// Phone intelligence — POST /intelligence/phone {number, region?}. Shows the
/// metadata analysis (valid, country, carrier/region, variants) + local matches.
class PhoneSearchScreen extends StatefulWidget {
  const PhoneSearchScreen({super.key, this.initialQuery});

  final String? initialQuery;

  @override
  State<PhoneSearchScreen> createState() => _PhoneSearchScreenState();
}

class _PhoneSearchScreenState extends State<PhoneSearchScreen> {
  late final TextEditingController _number =
      TextEditingController(text: widget.initialQuery ?? '');
  final TextEditingController _region = TextEditingController();
  bool _loading = false;
  String? _error;
  PhoneIntelligence? _result;

  @override
  void initState() {
    super.initState();
    if ((widget.initialQuery ?? '').trim().isNotEmpty) {
      WidgetsBinding.instance.addPostFrameCallback((_) => _run());
    }
  }

  @override
  void dispose() {
    _number.dispose();
    _region.dispose();
    super.dispose();
  }

  Future<void> _run() async {
    final number = _number.text.trim();
    if (number.isEmpty) return;
    FocusScope.of(context).unfocus();
    setState(() {
      _loading = true;
      _error = null;
      _result = null;
    });
    try {
      final region = _region.text.trim();
      final r = await ApiClient.instance.postJson('/intelligence/phone', {
        'number': number,
        if (region.isNotEmpty) 'region': region,
      });
      if (r.statusCode != 200) {
        setState(() => _error = 'Analysis failed (HTTP ${r.statusCode}).');
      } else {
        final data = jsonDecode(r.body) as Map<String, dynamic>;
        setState(() => _result = PhoneIntelligence.fromJson(data));
      }
    } catch (_) {
      setState(() => _error = 'Cannot reach backend. Check settings.');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final res = _result;
    final a = res?.analysis;
    return Scaffold(
      appBar: AppBar(title: const Text('Phone Intelligence')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: TextField(
                  controller: _number,
                  keyboardType: TextInputType.phone,
                  textInputAction: TextInputAction.search,
                  onSubmitted: (_) => _run(),
                  decoration: const InputDecoration(hintText: '+250788123456'),
                ),
              ),
              const SizedBox(width: 8),
              SizedBox(
                width: 84,
                child: TextField(
                  controller: _region,
                  maxLength: 2,
                  textCapitalization: TextCapitalization.characters,
                  decoration: const InputDecoration(
                      hintText: 'RW', counterText: ''),
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          SizedBox(
            width: double.infinity,
            child: FilledButton(
              style: FilledButton.styleFrom(
                  backgroundColor: KaiColors.accent, foregroundColor: Colors.black),
              onPressed: _loading ? null : _run,
              child: Text(_loading ? 'ANALYZING…' : 'ANALYZE'),
            ),
          ),
          const SizedBox(height: 16),
          if (_error != null)
            Text(_error!, style: const TextStyle(color: KaiColors.danger)),
          if (a != null && !_loading) ...[
            _card(
              header: 'ANALYSIS',
              headerRight: a.parsed
                  ? (a.valid ? 'VALID' : 'INVALID')
                  : 'UNPARSEABLE',
              headerRightColor:
                  a.valid ? KaiColors.verified : KaiColors.accent,
              child: a.parsed
                  ? Column(
                      children: [
                        _kv('E.164', a.e164),
                        _kv('International', a.international),
                        _kv('National', a.national),
                        _kv(
                            'Country',
                            a.countryCode != null
                                ? '+${a.countryCode} (${a.region ?? '—'})'
                                : null),
                        _kv('Location', a.location),
                        _kv('Carrier', a.carrier),
                        _kv('Type', a.numberType),
                        if (a.variants.isNotEmpty) ...[
                          const SizedBox(height: 10),
                          _chipsLabel('VARIANTS', a.variants),
                        ],
                      ],
                    )
                  : Text('Could not parse: ${a.error ?? 'unknown error'}',
                      style:
                          const TextStyle(color: KaiColors.muted, fontSize: 13)),
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
            Text(value ?? '—',
                style: const TextStyle(color: KaiColors.ink, fontSize: 13)),
          ],
        ),
      );

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
