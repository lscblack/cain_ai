import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:http_parser/http_parser.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Single-operator API client. Base URL is user-configurable (Settings) so the
/// same build works over a Cloudflare tunnel, LAN, or the Android emulator.
class ApiClient {
  ApiClient._();
  static final ApiClient instance = ApiClient._();

  // Default can be baked at build time (--dart-define=KAI_BASE_URL=...); otherwise
  // 10.0.2.2 is the host loopback from the Android emulator. Always overridable
  // in Settings (persisted).
  String baseUrl = const String.fromEnvironment(
    'KAI_BASE_URL',
    defaultValue: 'http://10.0.2.2:8001',
  );
  String? token;

  static const _storage = FlutterSecureStorage();

  Future<void> load() async {
    final prefs = await SharedPreferences.getInstance();
    baseUrl = prefs.getString('kai.baseUrl') ?? baseUrl;
    try {
      token = await _storage.read(key: 'kai.token');
    } catch (_) {
      token = null;
    }
  }

  bool get isLoggedIn => token != null && token!.isNotEmpty;

  Future<void> setBaseUrl(String url) async {
    baseUrl = url.trim().replaceAll(RegExp(r'/+$'), '');
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('kai.baseUrl', baseUrl);
  }

  Future<void> setToken(String? t) async {
    token = t;
    try {
      if (t == null) {
        await _storage.delete(key: 'kai.token');
      } else {
        await _storage.write(key: 'kai.token', value: t);
      }
    } catch (_) {}
  }

  // --- Credentials for biometric auto-login -------------------------------
  // Stored in the OS keystore-backed secure storage; the app only re-reads them
  // after a successful device biometric check (see UnlockScreen).

  Future<bool> hasCredentials() async {
    try {
      return (await _storage.read(key: 'kai.email')) != null;
    } catch (_) {
      return false;
    }
  }

  Future<void> _saveCredentials(String email, String password) async {
    try {
      await _storage.write(key: 'kai.email', value: email);
      await _storage.write(key: 'kai.password', value: password);
    } catch (_) {}
  }

  Future<void> clearCredentials() async {
    try {
      await _storage.delete(key: 'kai.email');
      await _storage.delete(key: 'kai.password');
    } catch (_) {}
  }

  /// Log in, persist the token AND (for biometric unlock) the credentials.
  /// Returns null on success, or an error message.
  Future<String?> login(String email, String password) async {
    try {
      final r = await postJson('/auth/login', {'email': email, 'password': password});
      if (r.statusCode == 200) {
        final t = jsonDecode(r.body)['access_token'] as String?;
        await setToken(t);
        await _saveCredentials(email, password);
        return null;
      }
      return 'Login failed (${r.statusCode}).';
    } catch (_) {
      return 'Cannot reach backend. Check the server URL in settings.';
    }
  }

  /// Apply a QR pairing payload scanned from the web app: {"u": backendUrl,
  /// "t": token}. Returns null on success, or a specific error message so the
  /// UI can distinguish "can't reach backend" from "bad/expired token".
  Future<String?> applyQrSession(String raw) async {
    Map data;
    try {
      final d = jsonDecode(raw);
      if (d is! Map) return "That QR isn't a KAI pairing code.";
      data = d;
    } catch (_) {
      return "That QR isn't a KAI pairing code.";
    }
    final url = data['u']?.toString();
    final tok = data['t']?.toString();
    if (url == null || url.isEmpty || tok == null || tok.isEmpty) {
      return "Pairing code is missing the server URL or token.";
    }
    await setBaseUrl(url);
    await setToken(tok);
    http.Response r;
    try {
      r = await getJson('/intelligence/face/status').timeout(const Duration(seconds: 8));
    } catch (_) {
      return "Can't reach the backend at $url.\nMake sure your phone is on the same Wi-Fi and the server is listening on the network.";
    }
    if (r.statusCode == 200) return null;
    if (r.statusCode == 401) return "Session expired — regenerate the QR on the web and scan again.";
    return "Backend responded HTTP ${r.statusCode}.";
  }

  /// Re-authenticate silently using stored credentials (after biometric unlock).
  Future<bool> loginWithStoredCreds() async {
    try {
      final email = await _storage.read(key: 'kai.email');
      final password = await _storage.read(key: 'kai.password');
      if (email == null || password == null) return false;
      return (await login(email, password)) == null;
    } catch (_) {
      return false;
    }
  }

  Map<String, String> get _authHeaders =>
      token != null ? {'Authorization': 'Bearer $token'} : {};

  Uri _uri(String path) => Uri.parse('$baseUrl$path');

  /// Full URL + auth headers for an authenticated image path (e.g. crop_url).
  String imageUrl(String path) => '$baseUrl$path';
  Map<String, String> get imageHeaders => _authHeaders;

  Future<http.Response> getJson(String path) =>
      http.get(_uri(path), headers: _authHeaders);

  Future<http.Response> postJson(String path, Map<String, dynamic> body) =>
      http.post(_uri(path),
          headers: {'Content-Type': 'application/json', ..._authHeaders},
          body: jsonEncode(body));

  Future<http.Response> postImage(
    String path,
    List<int> bytes, {
    String filename = 'image.jpg',
    String contentType = 'image/jpeg',
    Map<String, String> fields = const {},
  }) async {
    final req = http.MultipartRequest('POST', _uri(path));
    req.headers.addAll(_authHeaders);
    req.fields.addAll(fields);
    req.files.add(http.MultipartFile.fromBytes('file', bytes,
        filename: filename, contentType: MediaType.parse(contentType)));
    final streamed = await req.send();
    return http.Response.fromStream(streamed);
  }
}
