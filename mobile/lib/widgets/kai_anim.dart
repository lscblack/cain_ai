import 'package:flutter/material.dart';

import '../theme/hacker_theme.dart';

/// Tasteful, reusable motion primitives for the KAI "hacker console" vibe.
/// Deliberately subtle — implicit animations + a few lightweight controllers.

/// Staggered fade + slide-up reveal for list/grid items on first build.
/// Each item animates once; [index] offsets the start for a cascade.
class RevealIn extends StatefulWidget {
  final int index;
  final Widget child;
  final Duration duration;
  final Duration stagger;
  final double offsetY;

  const RevealIn({
    super.key,
    required this.child,
    this.index = 0,
    this.duration = const Duration(milliseconds: 420),
    this.stagger = const Duration(milliseconds: 70),
    this.offsetY = 16,
  });

  @override
  State<RevealIn> createState() => _RevealInState();
}

class _RevealInState extends State<RevealIn> with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(
    vsync: this,
    duration: widget.duration,
  );
  late final CurvedAnimation _curve =
      CurvedAnimation(parent: _c, curve: Curves.easeOutCubic);

  @override
  void initState() {
    super.initState();
    Future.delayed(widget.stagger * widget.index, () {
      if (mounted) _c.forward();
    });
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _curve,
      builder: (context, child) {
        final t = _curve.value;
        return Opacity(
          opacity: t,
          child: Transform.translate(
            offset: Offset(0, (1 - t) * widget.offsetY),
            child: child,
          ),
        );
      },
      child: widget.child,
    );
  }
}

/// A slowly pulsing cyan glow halo around [child] (e.g. the engine-online dot
/// or the voice FAB). The glow breathes; the child stays put.
class PulseGlow extends StatefulWidget {
  final Widget child;
  final Color color;
  final double minBlur;
  final double maxBlur;
  final double spread;
  final bool active;

  const PulseGlow({
    super.key,
    required this.child,
    this.color = KaiColors.hud,
    this.minBlur = 4,
    this.maxBlur = 16,
    this.spread = 1,
    this.active = true,
  });

  @override
  State<PulseGlow> createState() => _PulseGlowState();
}

class _PulseGlowState extends State<PulseGlow>
    with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 1600),
  );

  @override
  void initState() {
    super.initState();
    if (widget.active) _c.repeat(reverse: true);
  }

  @override
  void didUpdateWidget(covariant PulseGlow old) {
    super.didUpdateWidget(old);
    if (widget.active && !_c.isAnimating) {
      _c.repeat(reverse: true);
    } else if (!widget.active && _c.isAnimating) {
      _c.stop();
    }
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (!widget.active) return widget.child;
    return AnimatedBuilder(
      animation: _c,
      builder: (context, child) {
        final t = Curves.easeInOut.transform(_c.value);
        final blur = widget.minBlur + (widget.maxBlur - widget.minBlur) * t;
        return DecoratedBox(
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            boxShadow: [
              BoxShadow(
                color: widget.color.withValues(alpha: 0.25 + 0.45 * t),
                blurRadius: blur,
                spreadRadius: widget.spread * t,
              ),
            ],
          ),
          child: child,
        );
      },
      child: widget.child,
    );
  }
}

/// A thin cyan scanline that sweeps horizontally across its area, clipped to
/// the bounds — a quiet "live readout" motif for HUD headers / panels.
class HeaderSweep extends StatefulWidget {
  final double height;
  final Color color;
  const HeaderSweep({super.key, this.height = 2, this.color = KaiColors.hud});

  @override
  State<HeaderSweep> createState() => _HeaderSweepState();
}

class _HeaderSweepState extends State<HeaderSweep>
    with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 2600),
  )..repeat();

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return ClipRect(
      child: SizedBox(
        height: widget.height,
        width: double.infinity,
        child: AnimatedBuilder(
          animation: _c,
          builder: (context, _) {
            return FractionallySizedBox(
              widthFactor: 0.32,
              alignment: Alignment(-1 + 2 * _c.value, 0),
              child: Container(
                decoration: BoxDecoration(
                  gradient: LinearGradient(
                    colors: [
                      widget.color.withValues(alpha: 0),
                      widget.color.withValues(alpha: 0.9),
                      widget.color.withValues(alpha: 0),
                    ],
                  ),
                  boxShadow: [
                    BoxShadow(
                        color: widget.color.withValues(alpha: 0.5),
                        blurRadius: 6),
                  ],
                ),
              ),
            );
          },
        ),
      ),
    );
  }
}

/// Fade + slight scale-in used when results appear, so content doesn't pop.
class AppearFade extends StatelessWidget {
  final Widget child;
  final Duration duration;
  const AppearFade({
    super.key,
    required this.child,
    this.duration = const Duration(milliseconds: 360),
  });

  @override
  Widget build(BuildContext context) {
    return TweenAnimationBuilder<double>(
      tween: Tween(begin: 0, end: 1),
      duration: duration,
      curve: Curves.easeOut,
      builder: (context, t, child) => Opacity(
        opacity: t.clamp(0.0, 1.0),
        child: Transform.scale(
          scale: 0.98 + 0.02 * t,
          alignment: Alignment.topCenter,
          child: child,
        ),
      ),
      child: child,
    );
  }
}
