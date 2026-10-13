import 'dart:async';

import 'package:flutter/material.dart';
import 'package:permission_handler/permission_handler.dart';
import 'package:wifi_scan/wifi_scan.dart';

import '../theme/hacker_theme.dart';

/// PASSIVE Wi-Fi reconnaissance: lists radio signals (networks) broadcasting
/// around the device — read-only. It does NOT connect to anything. Connecting
/// to a network is done by the user through the phone's own Wi-Fi settings.
class SignalsScreen extends StatefulWidget {
  const SignalsScreen({super.key});

  @override
  State<SignalsScreen> createState() => _SignalsScreenState();
}

class _SignalsScreenState extends State<SignalsScreen> {
  List<WiFiAccessPoint> _aps = [];
  bool _scanning = false;
  String? _note;
  StreamSubscription<List<WiFiAccessPoint>>? _sub;

  @override
  void initState() {
    super.initState();
    _scan();
  }

  int _channel(int freqMhz) {
    if (freqMhz >= 2412 && freqMhz <= 2484) {
      return freqMhz == 2484 ? 14 : ((freqMhz - 2407) / 5).round();
    }
    if (freqMhz >= 5000 && freqMhz <= 5900) return ((freqMhz - 5000) / 5).round();
    if (freqMhz >= 5955) return ((freqMhz - 5950) / 5).round(); // 6 GHz
    return 0;
  }

  String _band(int freqMhz) =>
      freqMhz >= 5955 ? "6GHz" : freqMhz >= 5000 ? "5GHz" : "2.4GHz";

  String _security(String caps) {
    final c = caps.toUpperCase();
    if (c.contains("WPA3")) return "WPA3";
    if (c.contains("WPA2")) return "WPA2";
    if (c.contains("WPA")) return "WPA";
    if (c.contains("WEP")) return "WEP";
    return "OPEN";
  }

  Future<void> _scan() async {
    setState(() {
      _scanning = true;
      _note = null;
    });
    try {
      // Android requires location (+ nearby-wifi on 13+) to read scan results.
      await [Permission.locationWhenInUse, Permission.nearbyWifiDevices].request();
      final can = await WiFiScan.instance.canStartScan();
      if (can != CanStartScan.yes) {
        setState(() {
          _note = "Wi-Fi scan needs Location permission + Wi-Fi on. ($can)";
          _scanning = false;
        });
        return;
      }
      await WiFiScan.instance.startScan();
      await Future.delayed(const Duration(seconds: 2));
      final canGet = await WiFiScan.instance.canGetScannedResults();
      if (canGet != CanGetScannedResults.yes) {
        setState(() {
          _note = "Can't read results ($canGet).";
          _scanning = false;
        });
        return;
      }
      final results = await WiFiScan.instance.getScannedResults();
      results.sort((a, b) => b.level.compareTo(a.level)); // strongest first
      if (mounted) setState(() => _aps = results);
    } catch (e) {
      if (mounted) setState(() => _note = "Scan failed: $e");
    } finally {
      if (mounted) setState(() => _scanning = false);
    }
  }

  @override
  void dispose() {
    _sub?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Signals'),
        actions: [
          IconButton(
            icon: Icon(_scanning ? Icons.radar : Icons.refresh, color: KaiColors.hud),
            onPressed: _scanning ? null : _scan,
            tooltip: 'Re-scan',
          ),
        ],
      ),
      body: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 4),
            child: HudHeader('${_aps.length} RF signals nearby'),
          ),
          const Padding(
            padding: EdgeInsets.fromLTRB(16, 0, 16, 8),
            child: Text(
              'Passive scan — read-only. KAI does not connect to anything. '
              'To join a network, use your phone\'s Wi-Fi settings.',
              style: TextStyle(color: KaiColors.muted, fontSize: 11, height: 1.4),
            ),
          ),
          if (_note != null)
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: Text(_note!, style: const TextStyle(color: KaiColors.warn, fontSize: 12)),
            ),
          if (_scanning && _aps.isEmpty)
            const Padding(
              padding: EdgeInsets.all(24),
              child: Center(child: Text('scanning the airwaves…', style: TextStyle(color: KaiColors.hud))),
            ),
          Expanded(
            child: ListView.separated(
              padding: const EdgeInsets.all(16),
              itemCount: _aps.length,
              separatorBuilder: (_, __) => const SizedBox(height: 10),
              itemBuilder: (_, i) {
                final ap = _aps[i];
                final ssid = ap.ssid.isEmpty ? '<hidden network>' : ap.ssid;
                final sec = _security(ap.capabilities);
                final strength = ((ap.level + 100) / 60).clamp(0.0, 1.0);
                return HudPanel(
                  padding: const EdgeInsets.all(12),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(children: [
                        Icon(Icons.wifi,
                            size: 16,
                            color: sec == 'OPEN' ? KaiColors.warn : KaiColors.hud),
                        const SizedBox(width: 6),
                        Expanded(
                          child: Text(ssid,
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: const TextStyle(
                                  color: KaiColors.ink, fontWeight: FontWeight.bold)),
                        ),
                        Text('${ap.level} dBm',
                            style: const TextStyle(color: KaiColors.hud, fontSize: 12)),
                      ]),
                      const SizedBox(height: 6),
                      HudBar(strength),
                      const SizedBox(height: 6),
                      Wrap(spacing: 10, runSpacing: 2, children: [
                        _meta('SEC', sec, sec == 'OPEN' ? KaiColors.warn : KaiColors.verified),
                        _meta('BAND', _band(ap.frequency), KaiColors.muted),
                        _meta('CH', '${_channel(ap.frequency)}', KaiColors.muted),
                        _meta('MAC', ap.bssid, KaiColors.muted),
                      ]),
                    ],
                  ),
                );
              },
            ),
          ),
        ],
      ),
    );
  }

  Widget _meta(String k, String v, Color c) {
    return RichText(
      text: TextSpan(children: [
        TextSpan(text: '$k ', style: const TextStyle(color: KaiColors.muted, fontSize: 10, letterSpacing: 1)),
        TextSpan(text: v, style: TextStyle(color: c, fontSize: 11, fontFamily: 'monospace')),
      ]),
    );
  }
}
