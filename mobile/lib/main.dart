import 'package:flutter/material.dart';

import 'services/api_client.dart';
import 'theme/hacker_theme.dart';
import 'screens/home_screen.dart';
import 'screens/login_screen.dart';
import 'screens/unlock_screen.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await ApiClient.instance.load();
  // Open access: when the backend allows it, sign in silently so no login
  // screen is shown. Falls through to the normal flow if disabled/unreachable.
  var openAccess = ApiClient.instance.isLoggedIn;
  if (!openAccess) openAccess = await ApiClient.instance.openAccess();
  final hasCreds = await ApiClient.instance.hasCredentials();
  runApp(KaiApp(openAccess: openAccess, hasCredentials: hasCreds));
}

enum _Stage { unlock, login, home }

class KaiApp extends StatefulWidget {
  final bool openAccess;
  final bool hasCredentials;
  const KaiApp({super.key, required this.openAccess, required this.hasCredentials});

  @override
  State<KaiApp> createState() => _KaiAppState();
}

class _KaiAppState extends State<KaiApp> {
  late _Stage _stage = widget.openAccess
      ? _Stage.home
      : (widget.hasCredentials ? _Stage.unlock : _Stage.login);

  Future<void> _logout() async {
    await ApiClient.instance.setToken(null);
    await ApiClient.instance.clearCredentials();
    setState(() => _stage = _Stage.login);
  }

  @override
  Widget build(BuildContext context) {
    Widget screen;
    switch (_stage) {
      case _Stage.unlock:
        screen = UnlockScreen(
          onUnlocked: () => setState(() => _stage = _Stage.home),
          onUsePassword: () => setState(() => _stage = _Stage.login),
        );
        break;
      case _Stage.login:
        screen = LoginScreen(onLoggedIn: () => setState(() => _stage = _Stage.home));
        break;
      case _Stage.home:
        screen = HomeScreen(onLoggedOut: _logout);
        break;
    }
    return MaterialApp(
      title: 'KAI',
      debugShowCheckedModeBanner: false,
      theme: buildKaiTheme(),
      home: screen,
    );
  }
}
