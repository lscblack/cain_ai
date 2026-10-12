import 'dart:convert';

import 'package:flutter/material.dart';

import '../services/api_client.dart';
import '../theme/hacker_theme.dart';
import 'face_search_screen.dart';
import 'settings_screen.dart';

class HomeScreen extends StatefulWidget {
  final VoidCallback onLoggedOut;
  const HomeScreen({super.key, required this.onLoggedOut});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  bool? _engineOnline;

  @override
  void initState() {
    super.initState();
    _checkEngine();
  }

  Future<void> _checkEngine() async {
    try {
      final r = await ApiClient.instance.getJson('/intelligence/face/status');
      if (r.statusCode == 200) {
        setState(() => _engineOnline = jsonDecode(r.body)['available'] == true);
      } else {
        setState(() => _engineOnline = false);
      }
    } catch (_) {
      setState(() => _engineOnline = false);
    }
  }

  Future<void> _logout() async {
    await ApiClient.instance.setToken(null);
    widget.onLoggedOut();
  }

  @override
  Widget build(BuildContext context) {
    final tiles = <_Tile>[
      _Tile('Face Search', Icons.person_search, KaiColors.accent,
          () => Navigator.push(context, MaterialPageRoute(builder: (_) => const FaceSearchScreen()))),
      _Tile('Live Camera', Icons.videocam_outlined, KaiColors.verified, null, soon: true),
      _Tile('Video Search', Icons.movie_outlined, KaiColors.warn, null, soon: true),
      _Tile('Universal Search', Icons.search, KaiColors.ink, null, soon: true),
      _Tile('Phone', Icons.phone_outlined, KaiColors.ink, null, soon: true),
      _Tile('Email', Icons.alternate_email, KaiColors.ink, null, soon: true),
      _Tile('Username', Icons.person_outline, KaiColors.ink, null, soon: true),
      _Tile('Investigations', Icons.folder_outlined, KaiColors.ink, null, soon: true),
    ];

    return Scaffold(
      appBar: AppBar(
        title: Row(children: [
          const Text('KAI',
              style: TextStyle(
                  fontWeight: FontWeight.bold, letterSpacing: 3, color: KaiColors.accent)),
          const SizedBox(width: 10),
          if (_engineOnline != null)
            Text(
              _engineOnline! ? '● ENGINE ONLINE' : '● ENGINE OFFLINE',
              style: TextStyle(
                  fontSize: 10,
                  color: _engineOnline! ? KaiColors.accent : KaiColors.danger),
            ),
        ]),
        actions: [
          IconButton(
            icon: const Icon(Icons.settings),
            onPressed: () => Navigator.push(
                context, MaterialPageRoute(builder: (_) => const SettingsScreen())),
          ),
          IconButton(icon: const Icon(Icons.logout), onPressed: _logout),
        ],
      ),
      body: GridView.count(
        padding: const EdgeInsets.all(16),
        crossAxisCount: 2,
        mainAxisSpacing: 12,
        crossAxisSpacing: 12,
        childAspectRatio: 1.3,
        children: tiles.map((t) => _TileCard(tile: t)).toList(),
      ),
    );
  }
}

class _Tile {
  final String label;
  final IconData icon;
  final Color color;
  final VoidCallback? onTap;
  final bool soon;
  _Tile(this.label, this.icon, this.color, this.onTap, {this.soon = false});
}

class _TileCard extends StatelessWidget {
  final _Tile tile;
  const _TileCard({required this.tile});

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: tile.onTap ??
          () => ScaffoldMessenger.of(context).showSnackBar(
                const SnackBar(content: Text('Coming soon')),
              ),
      borderRadius: BorderRadius.circular(10),
      child: Container(
        decoration: BoxDecoration(
          color: KaiColors.panel,
          border: Border.all(color: KaiColors.line),
          borderRadius: BorderRadius.circular(10),
        ),
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(tile.icon, color: tile.color, size: 28),
            const Spacer(),
            Text(tile.label,
                style: const TextStyle(color: KaiColors.ink, fontWeight: FontWeight.bold)),
            if (tile.soon)
              const Text('coming soon',
                  style: TextStyle(color: KaiColors.muted, fontSize: 10)),
          ],
        ),
      ),
    );
  }
}
