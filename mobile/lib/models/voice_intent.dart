/// Voice-command intent model + a pure parser that maps a spoken transcript
/// to a structured [VoiceIntent].
///
/// This file is deliberately framework-free (no Flutter imports) so the parser
/// can be unit-tested in isolation and reused anywhere.
library;

/// The action a spoken command resolves to. The orchestrator wires each of
/// these to the correct destination screen (see README / handback notes).
enum VoiceAction {
  /// Open the face-search screen. Optional argument = a name to pre-fill.
  faceSearch,

  /// Open the live camera / real-time face scanner. No argument.
  liveCamera,

  /// Open video search. Optional argument = a query.
  videoSearch,

  /// Generic cross-source lookup. Argument = the free-text query.
  universalSearch,

  /// Phone-number lookup. Argument = the (cleaned) number.
  phone,

  /// Email lookup. Argument = the email address.
  email,

  /// Username / handle lookup. Argument = the username.
  username,

  /// Open the investigations / cases list. No argument.
  investigations,

  /// Nothing recognisable (e.g. empty transcript).
  unknown,
}

/// A parsed voice command: the [action], an optional [argument] (query, number,
/// address, name…) and the [transcript] it was derived from.
class VoiceIntent {
  final VoiceAction action;

  /// The payload for the action, or `null` when the action needs none
  /// (e.g. [VoiceAction.liveCamera]). Always trimmed; never an empty string.
  final String? argument;

  /// The raw transcript this intent was parsed from.
  final String transcript;

  const VoiceIntent({
    required this.action,
    this.argument,
    required this.transcript,
  });

  bool get hasArgument => argument != null && argument!.isNotEmpty;

  /// A short human-readable label for the action, e.g. for confirm UI.
  String get actionLabel {
    switch (action) {
      case VoiceAction.faceSearch:
        return 'FACE SEARCH';
      case VoiceAction.liveCamera:
        return 'LIVE CAMERA';
      case VoiceAction.videoSearch:
        return 'VIDEO SEARCH';
      case VoiceAction.universalSearch:
        return 'UNIVERSAL SEARCH';
      case VoiceAction.phone:
        return 'PHONE LOOKUP';
      case VoiceAction.email:
        return 'EMAIL LOOKUP';
      case VoiceAction.username:
        return 'USERNAME LOOKUP';
      case VoiceAction.investigations:
        return 'INVESTIGATIONS';
      case VoiceAction.unknown:
        return 'UNRECOGNISED';
    }
  }

  @override
  String toString() =>
      'VoiceIntent($action, arg=${argument ?? '-'}, "$transcript")';

  @override
  bool operator ==(Object other) =>
      other is VoiceIntent &&
      other.action == action &&
      other.argument == argument &&
      other.transcript == transcript;

  @override
  int get hashCode => Object.hash(action, argument, transcript);
}

/// Internal rule: a leading-phrase pattern mapped to an action. If [takesArg]
/// is true, whatever follows the matched phrase becomes the argument.
class _Rule {
  final RegExp pattern;
  final VoiceAction action;
  final bool takesArg;

  /// When true, the argument is reduced to digits / leading `+` (phone numbers).
  final bool digitsOnly;

  const _Rule(this.pattern, this.action,
      {this.takesArg = false, this.digitsOnly = false});
}

/// Filler words we drop from the front of an extracted argument,
/// e.g. "search for   the   john doe" -> "john doe".
final RegExp _leadingFiller =
    RegExp(r'^(for|the|a|an|of|to|my|is)\b\s*', caseSensitive: false);

/// Ordered rules. More specific phrases MUST come before the generic
/// "search / find" catch-all, otherwise e.g. "search video" would be read as a
/// universal search for the word "video".
final List<_Rule> _rules = <_Rule>[
  // --- Phone --------------------------------------------------------------
  // "search phone 250…", "phone number 250…", "phone 250…", "number 250…"
  _Rule(
    RegExp(r'^(search\s+)?(phone|mobile|cell)(\s+number)?\b[\s:,-]*',
        caseSensitive: false),
    VoiceAction.phone,
    takesArg: true,
    digitsOnly: true,
  ),
  _Rule(
    RegExp(r'^(search\s+)?(phone\s+)?number\b[\s:,-]*', caseSensitive: false),
    VoiceAction.phone,
    takesArg: true,
    digitsOnly: true,
  ),

  // --- Email --------------------------------------------------------------
  // "search email …", "email …", "e-mail …", "e mail …"
  _Rule(
    RegExp(r'^(search\s+)?e[\s\-]?mail(\s+address)?\b[\s:,-]*',
        caseSensitive: false),
    VoiceAction.email,
    takesArg: true,
  ),

  // --- Username -----------------------------------------------------------
  // "search username bob", "username bob", "user name bob", "handle bob"
  _Rule(
    RegExp(r'^(search\s+)?(username|user\s*name|handle|user)\b[\s:,-]*',
        caseSensitive: false),
    VoiceAction.username,
    takesArg: true,
  ),

  // --- Live camera --------------------------------------------------------
  // "open live camera", "live camera", "camera", "open camera", "scan live"
  _Rule(
    RegExp(r'^(open\s+|start\s+|search\s+)?(live\s+camera|camera|live\s+scan)\b',
        caseSensitive: false),
    VoiceAction.liveCamera,
  ),

  // --- Video search -------------------------------------------------------
  // "video search …", "search video …", "video …"
  _Rule(
    RegExp(r'^(open\s+)?(video\s+search|search\s+video|video)\b[\s:,-]*',
        caseSensitive: false),
    VoiceAction.videoSearch,
    takesArg: true,
  ),

  // --- Face search --------------------------------------------------------
  // "open face search", "face search", "search face", "face recognition",
  // "face …"
  _Rule(
    RegExp(
        r'^(open\s+|search\s+)?(face\s+search|face\s+recognition|facial|face)\b[\s:,-]*',
        caseSensitive: false),
    VoiceAction.faceSearch,
    takesArg: true,
  ),

  // --- Investigations -----------------------------------------------------
  // "open investigations", "investigations", "cases", "my cases", "case file"
  _Rule(
    RegExp(r'^(open\s+|show\s+|my\s+)?(investigations?|cases?|case\s+files?)\b',
        caseSensitive: false),
    VoiceAction.investigations,
  ),

  // --- Universal search (catch-all verb) ----------------------------------
  // "search …", "find …", "look up …", "lookup …", "who is …"
  _Rule(
    RegExp(r'^(search|find|look\s*up|lookup|who\s+is|whos)\b[\s:,-]*',
        caseSensitive: false),
    VoiceAction.universalSearch,
    takesArg: true,
  ),
];

/// Collapse runs of whitespace and trim.
String _normalise(String s) => s.trim().replaceAll(RegExp(r'\s+'), ' ');

/// Strip leading filler words from an extracted argument.
String _cleanArg(String s) {
  var out = s.trim();
  // Drop surrounding quotes a recogniser may add.
  out = out.replaceAll(RegExp(r'^["“]+|["”]+$'), '').trim();
  // Remove up to a couple of leading filler words.
  for (var i = 0; i < 2; i++) {
    final next = out.replaceFirst(_leadingFiller, '');
    if (next == out) break;
    out = next;
  }
  return out.trim();
}

/// Reduce a spoken phone argument to a clean number: digits plus an optional
/// leading `+`. Speech recognisers often insert spaces between digit groups,
/// so "250 788 123 456" becomes "250788123456".
String _digitsOnly(String s) {
  final hasPlus = s.trim().startsWith('+');
  final digits = s.replaceAll(RegExp(r'[^0-9]'), '');
  return hasPlus ? '+$digits' : digits;
}

/// Parse a spoken [transcript] into a structured [VoiceIntent].
///
/// Pure, case-insensitive and whitespace-tolerant. An empty/blank transcript
/// yields [VoiceAction.unknown]. Any phrase that matches no specific rule and
/// no generic search verb is treated as a bare [VoiceAction.universalSearch]
/// over the whole transcript (so a user can just say a name).
VoiceIntent parseVoiceCommand(String transcript) {
  final raw = transcript;
  final text = _normalise(transcript);

  if (text.isEmpty) {
    return VoiceIntent(action: VoiceAction.unknown, transcript: raw);
  }

  for (final rule in _rules) {
    final m = rule.pattern.firstMatch(text);
    if (m == null || m.start != 0) continue;

    String? arg;
    if (rule.takesArg) {
      final rest = _cleanArg(text.substring(m.end));
      if (rest.isNotEmpty) {
        arg = rule.digitsOnly ? _digitsOnly(rest) : rest;
        if (arg.isEmpty) arg = null;
      }
    }
    return VoiceIntent(action: rule.action, argument: arg, transcript: raw);
  }

  // No verb matched -> treat the whole utterance as a universal search query.
  return VoiceIntent(
    action: VoiceAction.universalSearch,
    argument: text,
    transcript: raw,
  );
}
