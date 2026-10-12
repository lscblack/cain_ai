import 'package:flutter/material.dart';

import '../services/api_client.dart';
import '../theme/hacker_theme.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  late final TextEditingController _url;
  String? _status;
  bool _testing = false;

  @override
  void initState() {
    super.initState();
    _url = TextEditingController(text: ApiClient.instance.baseUrl);
  }

  Future<void> _save() async {
    await ApiClient.instance.setBaseUrl(_url.text);
    setState(() => _status = 'Saved.');
  }

  Future<void> _test() async {
    await _save();
    setState(() {
      _testing = true;
      _status = null;
    });
    try {
      final r = await ApiClient.instance.getJson('/intelligence/face/status');
      setState(() => _status = r.statusCode == 200 || r.statusCode == 401
          ? '✓ Reachable (HTTP ${r.statusCode}).'
          : '⚠ Unexpected HTTP ${r.statusCode}.');
    } catch (e) {
      setState(() => _status = '✗ Not reachable. Check URL / tunnel.');
    } finally {
      setState(() => _testing = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Settings')),
      body: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('BACKEND SERVER URL',
                style: TextStyle(color: KaiColors.muted, fontSize: 11, letterSpacing: 1)),
            const SizedBox(height: 8),
            TextField(
              controller: _url,
              autocorrect: false,
              keyboardType: TextInputType.url,
              decoration: const InputDecoration(hintText: 'https://your-tunnel.trycloudflare.com'),
            ),
            const SizedBox(height: 8),
            const Text(
              'Use your Cloudflare tunnel HTTPS URL for remote access, your PC\'s LAN '
              'IP (e.g. http://192.168.1.x:8001) on the same Wi-Fi, or 10.0.2.2:8001 '
              'on the Android emulator.',
              style: TextStyle(color: KaiColors.muted, fontSize: 11, height: 1.4),
            ),
            const SizedBox(height: 16),
            Row(children: [
              FilledButton(
                style: FilledButton.styleFrom(
                    backgroundColor: KaiColors.panel2, foregroundColor: KaiColors.ink),
                onPressed: _save,
                child: const Text('Save'),
              ),
              const SizedBox(width: 12),
              OutlinedButton(
                onPressed: _testing ? null : _test,
                child: Text(_testing ? 'Testing…' : 'Test connection'),
              ),
            ]),
            if (_status != null) ...[
              const SizedBox(height: 16),
              Text(_status!, style: const TextStyle(color: KaiColors.accent)),
            ],
          ],
        ),
      ),
    );
  }
}
