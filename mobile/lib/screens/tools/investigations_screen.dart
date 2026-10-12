import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../models/intel_models.dart';
import '../../models/investigation.dart';
import '../../services/api_client.dart';
import '../../theme/hacker_theme.dart';

/// Investigations list — GET /investigations. Tapping a case opens its detail.
class InvestigationsScreen extends StatefulWidget {
  const InvestigationsScreen({super.key});

  @override
  State<InvestigationsScreen> createState() => _InvestigationsScreenState();
}

class _InvestigationsScreenState extends State<InvestigationsScreen> {
  bool _loading = true;
  String? _error;
  List<InvestigationDetail> _cases = [];

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final r = await ApiClient.instance.getJson('/investigations');
      if (r.statusCode != 200) {
        setState(() => _error = 'Failed to load (HTTP ${r.statusCode}).');
      } else {
        final list = (jsonDecode(r.body) as List)
            .map((e) =>
                InvestigationDetail.fromJson(e as Map<String, dynamic>))
            .toList();
        setState(() => _cases = list);
      }
    } catch (_) {
      setState(() => _error = 'Cannot reach backend. Check settings.');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Investigations')),
      body: RefreshIndicator(
        onRefresh: _load,
        color: KaiColors.accent,
        backgroundColor: KaiColors.panel,
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            if (_loading)
              const Padding(
                padding: EdgeInsets.symmetric(vertical: 40),
                child: Center(
                    child: Text('LOADING CASES…',
                        style:
                            TextStyle(color: KaiColors.muted, fontSize: 11))),
              ),
            if (_error != null)
              Text(_error!, style: const TextStyle(color: KaiColors.danger)),
            if (!_loading && _error == null && _cases.isEmpty)
              Container(
                padding: const EdgeInsets.all(24),
                decoration:
                    BoxDecoration(border: Border.all(color: KaiColors.line)),
                child: const Text('No investigations yet.',
                    style: TextStyle(color: KaiColors.muted, fontSize: 13)),
              ),
            ..._cases.map((c) => _caseCard(c)),
          ],
        ),
      ),
    );
  }

  Widget _caseCard(InvestigationDetail c) => InkWell(
        onTap: () => Navigator.of(context).push(MaterialPageRoute(
            builder: (_) => InvestigationDetailScreen(
                investigationId: c.id, code: c.code, name: c.name))),
        child: Container(
          margin: const EdgeInsets.only(bottom: 12),
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
                  Text(c.code,
                      style: const TextStyle(
                          color: KaiColors.muted, fontSize: 11)),
                  Text(c.status.toUpperCase(),
                      style: TextStyle(
                          color: c.status == 'open'
                              ? KaiColors.verified
                              : KaiColors.muted,
                          fontSize: 11)),
                ],
              ),
              const SizedBox(height: 6),
              Text(c.name,
                  style: const TextStyle(
                      color: KaiColors.ink,
                      fontSize: 14,
                      fontWeight: FontWeight.w600)),
              const SizedBox(height: 10),
              Row(
                children: [
                  _stat('ENT', c.entityCount),
                  const SizedBox(width: 16),
                  _stat('EVD', c.evidenceCount),
                  const SizedBox(width: 16),
                  _stat('REL', c.relationshipCount),
                ],
              ),
            ],
          ),
        ),
      );

  Widget _stat(String label, int n) => Text('$label $n',
      style: const TextStyle(color: KaiColors.muted, fontSize: 11));
}

/// Investigation detail — GET /investigations/{id} for the summary, plus
/// /entities and /evidence for the two tabs.
class InvestigationDetailScreen extends StatefulWidget {
  const InvestigationDetailScreen({
    super.key,
    required this.investigationId,
    this.code,
    this.name,
  });

  final String investigationId;
  final String? code;
  final String? name;

  @override
  State<InvestigationDetailScreen> createState() =>
      _InvestigationDetailScreenState();
}

class _InvestigationDetailScreenState extends State<InvestigationDetailScreen>
    with SingleTickerProviderStateMixin {
  late final TabController _tab = TabController(length: 2, vsync: this);
  bool _loading = true;
  String? _error;
  InvestigationDetail? _detail;
  List<KaiEntity> _entities = [];
  List<KaiEvidence> _evidence = [];

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _tab.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final id = widget.investigationId;
      final results = await Future.wait([
        ApiClient.instance.getJson('/investigations/$id'),
        ApiClient.instance.getJson('/investigations/$id/entities'),
        ApiClient.instance.getJson('/investigations/$id/evidence'),
      ]);
      if (results[0].statusCode != 200) {
        setState(() => _error = 'Failed to load (HTTP ${results[0].statusCode}).');
      } else {
        setState(() {
          _detail = InvestigationDetail.fromJson(
              jsonDecode(results[0].body) as Map<String, dynamic>);
          _entities = (jsonDecode(results[1].body) as List? ?? [])
              .map((e) => KaiEntity.fromJson(e as Map<String, dynamic>))
              .toList();
          _evidence = (jsonDecode(results[2].body) as List? ?? [])
              .map((e) => KaiEvidence.fromJson(e as Map<String, dynamic>))
              .toList();
        });
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
    final d = _detail;
    return Scaffold(
      appBar: AppBar(
        title: Text(d?.code ?? widget.code ?? 'Investigation'),
        bottom: _loading
            ? null
            : TabBar(
                controller: _tab,
                indicatorColor: KaiColors.accent,
                labelColor: KaiColors.ink,
                unselectedLabelColor: KaiColors.muted,
                labelStyle: const TextStyle(fontSize: 12),
                tabs: [
                  Tab(text: 'ENTITIES (${_entities.length})'),
                  Tab(text: 'EVIDENCE (${_evidence.length})'),
                ],
              ),
      ),
      body: _loading
          ? const Center(
              child: Text('LOADING…',
                  style: TextStyle(color: KaiColors.muted, fontSize: 11)))
          : _error != null
              ? Center(
                  child: Text(_error!,
                      style: const TextStyle(color: KaiColors.danger)))
              : Column(
                  children: [
                    Padding(
                      padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
                      child: Row(
                        children: [
                          Expanded(
                            child: Text(d?.name ?? widget.name ?? '',
                                style: const TextStyle(
                                    color: KaiColors.ink,
                                    fontSize: 15,
                                    fontWeight: FontWeight.w600)),
                          ),
                          Text((d?.status ?? 'open').toUpperCase(),
                              style: TextStyle(
                                  color: (d?.status ?? 'open') == 'open'
                                      ? KaiColors.verified
                                      : KaiColors.muted,
                                  fontSize: 11)),
                        ],
                      ),
                    ),
                    if (d?.description != null && d!.description!.isNotEmpty)
                      Padding(
                        padding: const EdgeInsets.fromLTRB(16, 0, 16, 4),
                        child: Text(d.description!,
                            style: const TextStyle(
                                color: KaiColors.muted, fontSize: 12)),
                      ),
                    Expanded(
                      child: TabBarView(
                        controller: _tab,
                        children: [
                          _entitiesTab(),
                          _evidenceTab(),
                        ],
                      ),
                    ),
                  ],
                ),
    );
  }

  Widget _entitiesTab() {
    if (_entities.isEmpty) {
      return _empty('No entities in this case.');
    }
    return ListView.builder(
      padding: const EdgeInsets.all(16),
      itemCount: _entities.length,
      itemBuilder: (_, i) {
        final e = _entities[i];
        return Container(
          margin: const EdgeInsets.only(bottom: 8),
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
          decoration: BoxDecoration(
            color: KaiColors.panel,
            border: Border.all(color: KaiColors.line),
            borderRadius: BorderRadius.circular(8),
          ),
          child: Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(e.value,
                        style: const TextStyle(
                            color: KaiColors.ink, fontSize: 13)),
                    if (e.label != null && e.label!.isNotEmpty)
                      Text(e.label!,
                          style: const TextStyle(
                              color: KaiColors.muted, fontSize: 11)),
                  ],
                ),
              ),
              Text(e.type.toUpperCase(),
                  style: const TextStyle(color: KaiColors.muted, fontSize: 11)),
            ],
          ),
        );
      },
    );
  }

  Widget _evidenceTab() {
    if (_evidence.isEmpty) {
      return _empty('No evidence in this case.');
    }
    return ListView.builder(
      padding: const EdgeInsets.all(16),
      itemCount: _evidence.length,
      itemBuilder: (_, i) {
        final ev = _evidence[i];
        return InkWell(
          onTap: () => _open(ev.sourceUrl),
          child: Container(
            margin: const EdgeInsets.only(bottom: 8),
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
            decoration: BoxDecoration(
              color: KaiColors.panel,
              border: Border.all(color: KaiColors.line),
              borderRadius: BorderRadius.circular(8),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Text(ev.type.toUpperCase(),
                        style: const TextStyle(
                            color: KaiColors.muted, fontSize: 11)),
                    if (ev.band != null)
                      Text(KaiColors.bandLabel(ev.band),
                          style: TextStyle(
                              color: KaiColors.band(ev.band), fontSize: 11)),
                  ],
                ),
                const SizedBox(height: 4),
                Text(ev.sourceUrl,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                        color: KaiColors.verified, fontSize: 13)),
              ],
            ),
          ),
        );
      },
    );
  }

  Widget _empty(String t) => Center(
        child: Text(t,
            style: const TextStyle(color: KaiColors.muted, fontSize: 13)),
      );
}
