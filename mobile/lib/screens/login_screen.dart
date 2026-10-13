import 'package:flutter/material.dart';

import '../services/api_client.dart';
import '../theme/hacker_theme.dart';
import 'qr_login_screen.dart';
import 'settings_screen.dart';

class LoginScreen extends StatefulWidget {
  final VoidCallback onLoggedIn;
  const LoginScreen({super.key, required this.onLoggedIn});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _email = TextEditingController();
  final _password = TextEditingController();
  bool _busy = false;
  String? _error;

  Future<void> _login() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    final err = await ApiClient.instance.login(_email.text.trim(), _password.text);
    if (!mounted) return;
    if (err == null) {
      widget.onLoggedIn();
    } else {
      setState(() => _error = err);
    }
    setState(() => _busy = false);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(children: [
                    const Text('KAI',
                        style: TextStyle(
                            fontSize: 32,
                            fontWeight: FontWeight.bold,
                            letterSpacing: 4,
                            color: KaiColors.hud)),
                    const Spacer(),
                    IconButton(
                      icon: const Icon(Icons.settings, color: KaiColors.muted),
                      onPressed: () => Navigator.push(context,
                          MaterialPageRoute(builder: (_) => const SettingsScreen())),
                    ),
                  ]),
                  const Text('KNOWLEDGE · ANALYSIS · INTELLIGENCE',
                      style: TextStyle(color: KaiColors.muted, fontSize: 11, letterSpacing: 2)),
                  const SizedBox(height: 32),
                  const Text('OPERATOR LOGIN',
                      style: TextStyle(color: KaiColors.muted, fontSize: 11, letterSpacing: 2)),
                  const SizedBox(height: 12),
                  TextField(
                    controller: _email,
                    keyboardType: TextInputType.emailAddress,
                    autocorrect: false,
                    decoration: const InputDecoration(hintText: 'email'),
                  ),
                  const SizedBox(height: 12),
                  TextField(
                    controller: _password,
                    obscureText: true,
                    onSubmitted: (_) => _login(),
                    decoration: const InputDecoration(hintText: 'password'),
                  ),
                  if (_error != null) ...[
                    const SizedBox(height: 12),
                    Text(_error!, style: const TextStyle(color: KaiColors.danger, fontSize: 12)),
                  ],
                  const SizedBox(height: 20),
                  SizedBox(
                    width: double.infinity,
                    child: FilledButton(
                      style: FilledButton.styleFrom(
                        backgroundColor: KaiColors.hud,
                        foregroundColor: Colors.black,
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
                        padding: const EdgeInsets.symmetric(vertical: 16),
                      ),
                      onPressed: _busy ? null : _login,
                      child: Text(_busy ? 'AUTHENTICATING…' : 'LOG IN',
                          style: const TextStyle(fontWeight: FontWeight.bold, letterSpacing: 1)),
                    ),
                  ),
                  const SizedBox(height: 12),
                  OutlinedButton.icon(
                    onPressed: _busy
                        ? null
                        : () => Navigator.push(
                              context,
                              MaterialPageRoute(
                                builder: (_) => QrLoginScreen(onLoggedIn: widget.onLoggedIn),
                              ),
                            ),
                    icon: const Icon(Icons.qr_code_scanner, size: 18),
                    label: const Text('Scan QR from web'),
                  ),
                  const SizedBox(height: 16),
                  Center(
                    child: TextButton.icon(
                      onPressed: () => Navigator.push(
                          context, MaterialPageRoute(builder: (_) => const SettingsScreen())),
                      icon: const Icon(Icons.dns_outlined, size: 14, color: KaiColors.muted),
                      label: Text('server: ${ApiClient.instance.baseUrl}',
                          style: const TextStyle(color: KaiColors.muted, fontSize: 10)),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
