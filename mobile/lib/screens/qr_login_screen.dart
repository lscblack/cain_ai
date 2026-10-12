import 'package:flutter/material.dart';
import 'package:mobile_scanner/mobile_scanner.dart';

import '../services/api_client.dart';
import '../theme/hacker_theme.dart';

/// Scan the QR shown by the web app ("Pair mobile") to configure the backend
/// URL + session token in one shot — no typing.
class QrLoginScreen extends StatefulWidget {
  final VoidCallback onLoggedIn;
  const QrLoginScreen({super.key, required this.onLoggedIn});

  @override
  State<QrLoginScreen> createState() => _QrLoginScreenState();
}

class _QrLoginScreenState extends State<QrLoginScreen> {
  final _controller = MobileScannerController(detectionSpeed: DetectionSpeed.noDuplicates);
  bool _handling = false;
  String? _status;

  Future<void> _onDetect(BarcodeCapture capture) async {
    if (_handling) return;
    final raw = capture.barcodes.isNotEmpty ? capture.barcodes.first.rawValue : null;
    if (raw == null || raw.isEmpty) return;
    setState(() {
      _handling = true;
      _status = 'Pairing…';
    });
    final ok = await ApiClient.instance.applyQrSession(raw);
    if (!mounted) return;
    if (ok) {
      widget.onLoggedIn();
    } else {
      setState(() {
        _status = 'Invalid or expired QR. Try again.';
        _handling = false;
      });
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Scan QR to log in')),
      body: Stack(
        alignment: Alignment.center,
        children: [
          MobileScanner(controller: _controller, onDetect: _onDetect),
          // viewfinder
          Container(
            width: 240,
            height: 240,
            decoration: BoxDecoration(
              border: Border.all(color: KaiColors.accent, width: 2),
              borderRadius: BorderRadius.circular(12),
            ),
          ),
          Positioned(
            bottom: 40,
            left: 24,
            right: 24,
            child: Column(
              children: [
                Text(
                  _status ?? 'Open the web app → "Pair mobile" → scan the QR',
                  textAlign: TextAlign.center,
                  style: TextStyle(
                    color: _status != null && _status!.startsWith('Invalid')
                        ? KaiColors.danger
                        : KaiColors.ink,
                    fontSize: 13,
                    backgroundColor: Colors.black54,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
