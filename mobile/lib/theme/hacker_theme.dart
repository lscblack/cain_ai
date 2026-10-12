import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

/// KAI "professional hacker" theme — near-black panels, monospace, green/amber
/// accents, confidence-band colours shared with the web UI.
class KaiColors {
  static const bg = Color(0xFF05070A);
  static const panel = Color(0xFF0B0F14);
  static const panel2 = Color(0xFF121820);
  static const line = Color(0xFF1E2731);
  static const ink = Color(0xFFC9D4DE);
  static const muted = Color(0xFF6B7A88);
  static const accent = Color(0xFF36D399); // green — primary / potential match
  static const warn = Color(0xFFFFB020); // amber — strong similarity
  static const danger = Color(0xFFF87272); // red
  static const verified = Color(0xFF4EA1FF);

  static Color band(String? b) {
    switch (b) {
      case 'potential_match':
        return accent;
      case 'strong_similarity':
        return warn;
      case 'possible_association':
        return muted;
      default:
        return muted;
    }
  }

  static String bandLabel(String? b) {
    switch (b) {
      case 'potential_match':
        return 'POTENTIAL MATCH';
      case 'strong_similarity':
        return 'STRONG SIMILARITY';
      case 'possible_association':
        return 'POSSIBLE ASSOCIATION';
      case 'no_match':
        return 'NO MATCH';
      default:
        return (b ?? '').toUpperCase();
    }
  }
}

ThemeData buildKaiTheme() {
  final base = ThemeData.dark(useMaterial3: true);
  final mono = GoogleFonts.jetBrainsMonoTextTheme(base.textTheme).apply(
    bodyColor: KaiColors.ink,
    displayColor: KaiColors.ink,
  );
  return base.copyWith(
    scaffoldBackgroundColor: KaiColors.bg,
    colorScheme: base.colorScheme.copyWith(
      primary: KaiColors.accent,
      secondary: KaiColors.verified,
      surface: KaiColors.panel,
      error: KaiColors.danger,
    ),
    textTheme: mono,
    appBarTheme: const AppBarTheme(
      backgroundColor: KaiColors.bg,
      foregroundColor: KaiColors.ink,
      elevation: 0,
      centerTitle: false,
    ),
    cardTheme: const CardThemeData(
      color: KaiColors.panel,
      elevation: 0,
      shape: RoundedRectangleBorder(
        side: BorderSide(color: KaiColors.line),
        borderRadius: BorderRadius.all(Radius.circular(10)),
      ),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: KaiColors.panel,
      hintStyle: const TextStyle(color: KaiColors.muted),
      enabledBorder: OutlineInputBorder(
        borderSide: const BorderSide(color: KaiColors.line),
        borderRadius: BorderRadius.circular(8),
      ),
      focusedBorder: OutlineInputBorder(
        borderSide: const BorderSide(color: KaiColors.accent),
        borderRadius: BorderRadius.circular(8),
      ),
    ),
    dividerColor: KaiColors.line,
  );
}
