import 'dart:convert';

import 'package:flutter/material.dart';

import '../models/voice_intent.dart';
import '../services/api_client.dart';
import '../theme/hacker_theme.dart';
import 'face_search_screen.dart';
import 'live_camera_screen.dart';
import 'settings_screen.dart';
import 'video_search_screen.dart';
import 'voice_command_screen.dart';
import 'tools/universal_search_screen.dart';
import 'tools/phone_search_screen.dart';
import 'tools/email_search_screen.dart';
import 'tools/username_search_screen.dart';
import 'tools/investigations_screen.dart';

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

  void _go(Widget screen) {
    Navigator.push(context, MaterialPageRoute(builder: (_) => screen));
  }

  /// Route a parsed voice command to the right screen ("Jarvis").
  void _routeIntent(VoiceIntent intent) {
    final arg = intent.argument;
    switch (intent.action) {
      case VoiceAction.faceSearch:
        _go(const FaceSearchScreen());
        break;
      case VoiceAction.liveCamera:
        _go(const LiveCameraScreen());
        break;
      case VoiceAction.videoSearch:
        _go(const VideoSearchScreen());
        break;
      case VoiceAction.universalSearch:
        _go(UniversalSearchScreen(initialQuery: arg));
        break;
      case VoiceAction.phone:
        _go(PhoneSearchScreen(initialQuery: arg));
        break;
      case VoiceAction.email:
        _go(EmailSearchScreen(initialQuery: arg));
        break;
      case VoiceAction.username:
        _go(UsernameSearchScreen(initialQuery: arg));
        break;
      case VoiceAction.investigations:
        _go(const InvestigationsScreen());
        break;
      case VoiceAction.unknown:
        ScaffoldMessenger.of(context)
            .showSnackBar(const SnackBar(content: Text("Didn't catch a command")));
        break;
    }
  }

  void _openVoice() {
    Navigator.push(
      context,
      MaterialPageRoute(
        builder: (_) => VoiceCommandScreen(onIntent: (intent) {
          Navigator.pop(context); // close the voice screen first
          _routeIntent(intent);
        }),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final tiles = <_Tile>[
      _Tile('Face Search', Icons.person_search, KaiColors.accent,
          () => _go(const FaceSearchScreen())),
      _Tile('Live Detection', Icons.videocam_outlined, KaiColors.accent,
          () => _go(const LiveCameraScreen())),
      _Tile('Universal Search', Icons.search, KaiColors.ink,
          () => _go(const UniversalSearchScreen())),
      _Tile('Phone', Icons.phone_outlined, KaiColors.verified,
          () => _go(const PhoneSearchScreen())),
      _Tile('Email', Icons.alternate_email, KaiColors.verified,
          () => _go(const EmailSearchScreen())),
      _Tile('Username', Icons.person_search_outlined, KaiColors.verified,
          () => _go(const UsernameSearchScreen())),
      _Tile('Investigations', Icons.folder_open_outlined, KaiColors.warn,
          () => _go(const InvestigationsScreen())),
      _Tile('Video Search', Icons.video_library_outlined, KaiColors.accent,
          () => _go(const VideoSearchScreen())),
      _Tile('Voice (Jarvis)', Icons.mic, KaiColors.accent, _openVoice),
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
      floatingActionButton: FloatingActionButton(
        onPressed: _openVoice,
        backgroundColor: KaiColors.accent,
        foregroundColor: KaiColors.bg,
        tooltip: 'Voice command',
        child: const Icon(Icons.mic),
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
  _Tile(this.label, this.icon, this.color, this.onTap);
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
          ],
        ),
      ),
    );
  }
}
