import 'package:flutter/material.dart';
import 'package:local_auth/local_auth.dart';

import '../services/api_client.dart';
import '../theme/hacker_theme.dart';

/// Biometric gate: on launch, unlock with the device fingerprint/face and
/// silently re-authenticate with stored credentials — no typing a login.
class UnlockScreen extends StatefulWidget {
  final VoidCallback onUnlocked;
  final VoidCallback onUsePassword;
  const UnlockScreen({super.key, required this.onUnlocked, required this.onUsePassword});

  @override
  State<UnlockScreen> createState() => _UnlockScreenState();
}

class _UnlockScreenState extends State<UnlockScreen> {
  final _auth = LocalAuthentication();
  String _status = 'Authenticating…';
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _authenticate());
  }

  Future<void> _authenticate() async {
    if (_busy) return;
    setState(() {
      _busy = true;
      _status = 'Authenticating…';
    });
    try {
      bool ok = false;
      try {
        final supported = await _auth.isDeviceSupported();
        final canCheck = await _auth.canCheckBiometrics;
        if (supported || canCheck) {
          ok = await _auth.authenticate(
            localizedReason: 'Unlock KAI',
            biometricOnly: false, // allow device PIN/pattern as fallback
            persistAcrossBackgrounding: true,
          );
        } else {
          // No biometrics/lock set up — fall through to stored-session unlock.
          ok = true;
        }
      } on Exception {
        ok = false;
      }

      if (!ok) {
        setState(() {
          _busy = false;
          _status = 'Locked';
        });
        return;
      }

      setState(() => _status = 'Signing in…');
      final signedIn = await ApiClient.instance.loginWithStoredCreds();
      if (!mounted) return;
      if (signedIn) {
        widget.onUnlocked();
      } else {
        // Stored creds invalid/expired or backend unreachable → manual login.
        setState(() {
          _busy = false;
          _status = 'Session expired — sign in again.';
        });
      }
    } catch (_) {
      if (mounted) {
        setState(() {
          _busy = false;
          _status = 'Unlock failed.';
        });
      }
    }
  }

  void _usePassword() => widget.onUsePassword();

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text('KAI',
                style: TextStyle(
                    fontSize: 36,
                    fontWeight: FontWeight.bold,
                    letterSpacing: 6,
                    color: KaiColors.accent)),
            const SizedBox(height: 40),
            InkWell(
              onTap: _busy ? null : _authenticate,
              borderRadius: BorderRadius.circular(80),
              child: Container(
                padding: const EdgeInsets.all(28),
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  border: Border.all(color: KaiColors.accent, width: 2),
                  color: KaiColors.panel,
                ),
                child: const Icon(Icons.fingerprint, size: 72, color: KaiColors.accent),
              ),
            ),
            const SizedBox(height: 24),
            Text(_status, style: const TextStyle(color: KaiColors.muted, fontSize: 13)),
            const SizedBox(height: 32),
            if (!_busy)
              TextButton(
                onPressed: _authenticate,
                child: const Text('Try again', style: TextStyle(color: KaiColors.verified)),
              ),
            TextButton(
              onPressed: _usePassword,
              child: const Text('Use password instead',
                  style: TextStyle(color: KaiColors.muted)),
            ),
          ],
        ),
      ),
    );
  }
}
