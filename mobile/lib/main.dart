import 'package:flutter/material.dart';

import 'services/api_client.dart';
import 'theme/hacker_theme.dart';
import 'screens/home_screen.dart';
import 'screens/login_screen.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await ApiClient.instance.load();
  runApp(const KaiApp());
}

class KaiApp extends StatefulWidget {
  const KaiApp({super.key});

  @override
  State<KaiApp> createState() => _KaiAppState();
}

class _KaiAppState extends State<KaiApp> {
  bool _loggedIn = ApiClient.instance.isLoggedIn;

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'KAI',
      debugShowCheckedModeBanner: false,
      theme: buildKaiTheme(),
      home: _loggedIn
          ? HomeScreen(onLoggedOut: () => setState(() => _loggedIn = false))
          : LoginScreen(onLoggedIn: () => setState(() => _loggedIn = true)),
    );
  }
}
