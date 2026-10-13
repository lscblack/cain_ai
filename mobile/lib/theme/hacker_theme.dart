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
  static const hud = Color(0xFF22D3EE); // cyan — HUD accent
  static const hudDim = Color(0x4722D3EE); // cyan @ ~28%

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
      primary: KaiColors.hud, // cyan HUD accent
      secondary: KaiColors.accent,
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
        borderSide: const BorderSide(color: KaiColors.hud),
        borderRadius: BorderRadius.circular(8),
      ),
    ),
    dividerColor: KaiColors.line,
  );
}

/// Sci-fi HUD panel: cyan glowing border with corner brackets.
class HudPanel extends StatelessWidget {
  final Widget child;
  final EdgeInsetsGeometry padding;
  const HudPanel({super.key, required this.child, this.padding = const EdgeInsets.all(14)});

  @override
  Widget build(BuildContext context) {
    return Stack(
      children: [
        Container(
          width: double.infinity,
          padding: padding,
          decoration: BoxDecoration(
            color: KaiColors.panel2,
            border: Border.all(color: KaiColors.hudDim),
            borderRadius: BorderRadius.circular(6),
            boxShadow: const [BoxShadow(color: Color(0x1422D3EE), blurRadius: 18)],
          ),
          child: child,
        ),
        const Positioned(top: 0, left: 0, child: _Corner(topLeft: true)),
        const Positioned(bottom: 0, right: 0, child: _Corner(topLeft: false)),
      ],
    );
  }
}

class _Corner extends StatelessWidget {
  final bool topLeft;
  const _Corner({required this.topLeft});
  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: 12,
      height: 12,
      child: CustomPaint(painter: _CornerPainter(topLeft)),
    );
  }
}

class _CornerPainter extends CustomPainter {
  final bool topLeft;
  _CornerPainter(this.topLeft);
  @override
  void paint(Canvas canvas, Size s) {
    final p = Paint()
      ..color = KaiColors.hud
      ..strokeWidth = 1.5
      ..style = PaintingStyle.stroke;
    if (topLeft) {
      canvas.drawLine(const Offset(0, 0), Offset(s.width, 0), p);
      canvas.drawLine(const Offset(0, 0), Offset(0, s.height), p);
    } else {
      canvas.drawLine(Offset(s.width, s.height), Offset(0, s.height), p);
      canvas.drawLine(Offset(s.width, s.height), Offset(s.width, 0), p);
    }
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}

/// "◢ TITLE" HUD section header in cyan mono with a soft glow.
class HudHeader extends StatelessWidget {
  final String text;
  const HudHeader(this.text, {super.key});
  @override
  Widget build(BuildContext context) {
    return Text(
      '◢ ${text.toUpperCase()}',
      style: const TextStyle(
        color: KaiColors.hud,
        fontSize: 12,
        letterSpacing: 1.5,
        fontWeight: FontWeight.w600,
        shadows: [Shadow(color: Color(0x8822D3EE), blurRadius: 8)],
      ),
    );
  }
}

/// Thin cyan stat bar (0..1 fill).
class HudBar extends StatelessWidget {
  final double value; // 0..1
  const HudBar(this.value, {super.key});
  @override
  Widget build(BuildContext context) {
    return Container(
      height: 6,
      decoration: BoxDecoration(
        color: KaiColors.panel,
        border: Border.all(color: KaiColors.line),
      ),
      child: FractionallySizedBox(
        alignment: Alignment.centerLeft,
        widthFactor: value.clamp(0.0, 1.0),
        child: Container(
          decoration: const BoxDecoration(
            color: KaiColors.hud,
            boxShadow: [BoxShadow(color: Color(0x8822D3EE), blurRadius: 6)],
          ),
        ),
      ),
    );
  }
}
