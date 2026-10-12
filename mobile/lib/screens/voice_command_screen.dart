import 'package:flutter/material.dart';
import 'package:permission_handler/permission_handler.dart';
import 'package:speech_to_text/speech_recognition_error.dart';
import 'package:speech_to_text/speech_recognition_result.dart';
import 'package:speech_to_text/speech_to_text.dart';

import '../models/voice_intent.dart';
import '../theme/hacker_theme.dart';

/// "Jarvis" voice command surface. Captures speech, shows a live hacker-style
/// listening visual, parses the final transcript into a [VoiceIntent] and hands
/// it back to the caller via [onIntent] (which the orchestrator routes to the
/// right screen).
class VoiceCommandScreen extends StatefulWidget {
  /// Called when the user confirms a recognised command.
  final void Function(VoiceIntent intent) onIntent;

  const VoiceCommandScreen({super.key, required this.onIntent});

  @override
  State<VoiceCommandScreen> createState() => _VoiceCommandScreenState();
}

class _VoiceCommandScreenState extends State<VoiceCommandScreen>
    with SingleTickerProviderStateMixin {
  final SpeechToText _speech = SpeechToText();
  late final AnimationController _pulse;

  bool _initialised = false; // init() has run
  bool _available = false; // recogniser usable
  bool _listening = false;
  String _words = '';
  String? _error;
  VoiceIntent? _intent;

  static const List<String> _examples = [
    'search phone +250 788 123 456',
    'email jane@example.com',
    'username nightowl',
    'open live camera',
    'video search red hoodie suspect',
    'open face search',
    'open investigations',
    'find Jane Doe',
  ];

  @override
  void initState() {
    super.initState();
    _pulse = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1600),
    )..repeat();
    _init();
  }

  Future<void> _init() async {
    try {
      // Ask for the mic explicitly; speech_to_text also checks, but this gives
      // us a clean, themed denial path.
      final status = await Permission.microphone.request();
      if (!status.isGranted) {
        setState(() {
          _initialised = true;
          _available = false;
          _error = status.isPermanentlyDenied
              ? 'MICROPHONE PERMANENTLY DENIED — enable it in system settings.'
              : 'MICROPHONE ACCESS DENIED.';
        });
        return;
      }

      final ok = await _speech.initialize(
        onStatus: _onStatus,
        onError: _onError,
      );
      if (!mounted) return;
      setState(() {
        _initialised = true;
        _available = ok;
        if (!ok) _error = 'SPEECH RECOGNITION UNAVAILABLE on this device.';
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _initialised = true;
        _available = false;
        _error = 'VOICE ENGINE INIT FAILED.';
      });
    }
  }

  void _onStatus(String status) {
    final listening = status == SpeechToText.listeningStatus;
    if (mounted && listening != _listening) {
      setState(() => _listening = listening);
    }
  }

  void _onError(SpeechRecognitionError error) {
    if (!mounted) return;
    setState(() {
      _listening = false;
      _error = 'RECOGNITION ERROR: ${error.errorMsg}';
    });
  }

  Future<void> _toggle() async {
    if (!_available) return;
    if (_listening) {
      await _speech.stop();
      if (mounted) setState(() => _listening = false);
      return;
    }
    setState(() {
      _words = '';
      _intent = null;
      _error = null;
      _listening = true;
    });
    await _speech.listen(
      onResult: _onResult,
      listenOptions: SpeechListenOptions(
        partialResults: true,
        cancelOnError: true,
        listenMode: ListenMode.search,
      ),
    );
  }

  void _onResult(SpeechRecognitionResult result) {
    if (!mounted) return;
    setState(() => _words = result.recognizedWords);
    if (result.finalResult) {
      final intent = parseVoiceCommand(result.recognizedWords);
      setState(() {
        _listening = false;
        _intent = intent;
      });
    }
  }

  void _confirm() {
    final intent = _intent;
    if (intent == null) return;
    widget.onIntent(intent);
  }

  @override
  void dispose() {
    _pulse.dispose();
    // Fire-and-forget: tear down the recogniser.
    _speech.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('VOICE COMMAND',
            style: TextStyle(letterSpacing: 2, fontSize: 15)),
      ),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(20, 16, 20, 28),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              _statusLine(),
              const SizedBox(height: 28),
              Center(child: _micOrb()),
              const SizedBox(height: 24),
              _transcriptPanel(),
              if (_intent != null) ...[
                const SizedBox(height: 16),
                _intentPanel(_intent!),
              ],
              if (_error != null) ...[
                const SizedBox(height: 16),
                _errorPanel(_error!),
              ],
              const SizedBox(height: 28),
              _examplesPanel(),
            ],
          ),
        ),
      ),
    );
  }

  Widget _statusLine() {
    final (color, label) = switch ((_initialised, _available, _listening)) {
      (false, _, _) => (KaiColors.muted, 'INITIALISING…'),
      (_, false, _) => (KaiColors.danger, 'OFFLINE'),
      (_, _, true) => (KaiColors.accent, 'LISTENING'),
      _ => (KaiColors.verified, 'READY'),
    };
    return Row(
      children: [
        Container(
          width: 8,
          height: 8,
          decoration: BoxDecoration(color: color, shape: BoxShape.circle),
        ),
        const SizedBox(width: 8),
        Text(label,
            style: TextStyle(color: color, fontSize: 12, letterSpacing: 2)),
        const Spacer(),
        const Text('“JARVIS”',
            style: TextStyle(color: KaiColors.muted, fontSize: 12)),
      ],
    );
  }

  /// Big central mic button with pulsing concentric rings while listening.
  Widget _micOrb() {
    final active = _listening;
    return GestureDetector(
      onTap: _available ? _toggle : null,
      child: SizedBox(
        width: 240,
        height: 240,
        child: AnimatedBuilder(
          animation: _pulse,
          builder: (context, child) {
            return Stack(
              alignment: Alignment.center,
              children: [
                if (active) ..._rings(),
                // Core disc.
                Container(
                  width: 120,
                  height: 120,
                  decoration: BoxDecoration(
                    color: KaiColors.panel2,
                    shape: BoxShape.circle,
                    border: Border.all(
                      color: active ? KaiColors.accent : KaiColors.line,
                      width: 2,
                    ),
                    boxShadow: active
                        ? [
                            BoxShadow(
                              color: KaiColors.accent.withValues(alpha: 0.35),
                              blurRadius: 24,
                              spreadRadius: 2,
                            ),
                          ]
                        : null,
                  ),
                  child: Icon(
                    active ? Icons.graphic_eq : Icons.mic_none,
                    size: 48,
                    color: _available
                        ? (active ? KaiColors.accent : KaiColors.ink)
                        : KaiColors.muted,
                  ),
                ),
              ],
            );
          },
        ),
      ),
    );
  }

  List<Widget> _rings() {
    // Three staggered expanding/fading rings driven by the pulse controller.
    return List.generate(3, (i) {
      final t = (_pulse.value + i / 3) % 1.0;
      final size = 120 + t * 120;
      final opacity = (1.0 - t) * 0.5;
      return Opacity(
        opacity: opacity.clamp(0.0, 1.0),
        child: Container(
          width: size,
          height: size,
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            border: Border.all(color: KaiColors.accent, width: 1.5),
          ),
        ),
      );
    });
  }

  Widget _transcriptPanel() {
    final showing = _words.isNotEmpty;
    return Container(
      width: double.infinity,
      constraints: const BoxConstraints(minHeight: 72),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: KaiColors.panel,
        border: Border.all(color: KaiColors.line),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(_listening ? 'HEARING…' : 'TRANSCRIPT',
              style: const TextStyle(
                  color: KaiColors.muted, fontSize: 10, letterSpacing: 2)),
          const SizedBox(height: 6),
          Text(
            showing
                ? _words
                : (_available
                    ? 'Tap the mic and speak a command.'
                    : 'Voice input is not available.'),
            style: TextStyle(
              color: showing ? KaiColors.ink : KaiColors.muted,
              fontSize: 16,
              height: 1.35,
            ),
          ),
        ],
      ),
    );
  }

  Widget _intentPanel(VoiceIntent intent) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: KaiColors.panel2,
        border: Border.all(color: KaiColors.accent),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.bolt, size: 16, color: KaiColors.accent),
              const SizedBox(width: 6),
              Text('RECOGNISED → ${intent.actionLabel}',
                  style: const TextStyle(
                      color: KaiColors.accent,
                      fontSize: 12,
                      letterSpacing: 1)),
            ],
          ),
          if (intent.hasArgument) ...[
            const SizedBox(height: 8),
            Text(intent.argument!,
                style: const TextStyle(color: KaiColors.ink, fontSize: 16)),
          ],
          const SizedBox(height: 14),
          Row(
            children: [
              Expanded(
                child: FilledButton.icon(
                  style: FilledButton.styleFrom(
                    backgroundColor: KaiColors.accent,
                    foregroundColor: KaiColors.bg,
                  ),
                  onPressed: _confirm,
                  icon: const Icon(Icons.play_arrow),
                  label: const Text('EXECUTE'),
                ),
              ),
              const SizedBox(width: 10),
              OutlinedButton.icon(
                style: OutlinedButton.styleFrom(
                  foregroundColor: KaiColors.muted,
                  side: const BorderSide(color: KaiColors.line),
                ),
                onPressed: _available ? _toggle : null,
                icon: const Icon(Icons.refresh),
                label: const Text('RETRY'),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _errorPanel(String message) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: KaiColors.panel,
        border: Border.all(color: KaiColors.danger),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Row(
        children: [
          const Icon(Icons.error_outline, size: 18, color: KaiColors.danger),
          const SizedBox(width: 10),
          Expanded(
            child: Text(message,
                style: const TextStyle(color: KaiColors.danger, fontSize: 13)),
          ),
          if (_error != null && _error!.contains('PERMANENTLY'))
            TextButton(
              onPressed: openAppSettings,
              child: const Text('SETTINGS'),
            ),
        ],
      ),
    );
  }

  Widget _examplesPanel() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text('TRY SAYING…',
            style: TextStyle(
                color: KaiColors.muted, fontSize: 10, letterSpacing: 2)),
        const SizedBox(height: 10),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: _examples
              .map((e) => Container(
                    padding:
                        const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
                    decoration: BoxDecoration(
                      color: KaiColors.panel,
                      border: Border.all(color: KaiColors.line),
                      borderRadius: BorderRadius.circular(6),
                    ),
                    child: Text('“$e”',
                        style: const TextStyle(
                            color: KaiColors.ink, fontSize: 12)),
                  ))
              .toList(),
        ),
      ],
    );
  }
}
