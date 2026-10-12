import 'package:flutter_test/flutter_test.dart';
import 'package:kai_mobile/models/voice_intent.dart';

void main() {
  VoiceIntent p(String s) => parseVoiceCommand(s);

  group('phone', () {
    test('search phone <number>', () {
      final i = p('search phone +250 788 123 456');
      expect(i.action, VoiceAction.phone);
      expect(i.argument, '+250788123456');
    });
    test('bare "phone <number>"', () {
      expect(p('phone 0788123456').action, VoiceAction.phone);
      expect(p('phone 0788123456').argument, '0788123456');
    });
    test('"phone number <n>" and "number <n>"', () {
      expect(p('phone number 250788').action, VoiceAction.phone);
      expect(p('number 250788').action, VoiceAction.phone);
      expect(p('number 250788').argument, '250788');
    });
    test('mobile / cell synonyms', () {
      expect(p('mobile 123456').action, VoiceAction.phone);
      expect(p('search cell 123456').action, VoiceAction.phone);
    });
    test('digits are extracted from spoken spacing', () {
      expect(p('phone two 50 788').argument, '50788');
    });
  });

  group('email', () {
    test('search email', () {
      final i = p('search email jane@example.com');
      expect(i.action, VoiceAction.email);
      expect(i.argument, 'jane@example.com');
    });
    test('bare email + e-mail variants', () {
      expect(p('email bob@test.io').action, VoiceAction.email);
      expect(p('e-mail bob@test.io').action, VoiceAction.email);
      expect(p('email address bob@test.io').argument, 'bob@test.io');
    });
  });

  group('username', () {
    test('search username / username / handle / user', () {
      expect(p('search username nightowl').action, VoiceAction.username);
      expect(p('username nightowl').argument, 'nightowl');
      expect(p('user name nightowl').action, VoiceAction.username);
      expect(p('handle nightowl').action, VoiceAction.username);
      expect(p('user nightowl').action, VoiceAction.username);
    });
  });

  group('live camera', () {
    test('phrasings resolve with no argument', () {
      for (final s in [
        'open live camera',
        'live camera',
        'camera',
        'open camera',
        'live scan',
      ]) {
        final i = p(s);
        expect(i.action, VoiceAction.liveCamera, reason: s);
        expect(i.argument, isNull, reason: s);
      }
    });
  });

  group('video search', () {
    test('video search / search video / video <query>', () {
      expect(p('video search').action, VoiceAction.videoSearch);
      expect(p('search video').action, VoiceAction.videoSearch);
      final i = p('video search red hoodie');
      expect(i.action, VoiceAction.videoSearch);
      expect(i.argument, 'red hoodie');
    });
  });

  group('face search', () {
    test('open face search / face search / search face / face', () {
      expect(p('open face search').action, VoiceAction.faceSearch);
      expect(p('face search').action, VoiceAction.faceSearch);
      expect(p('search face').action, VoiceAction.faceSearch);
      expect(p('face recognition').action, VoiceAction.faceSearch);
      expect(p('face').action, VoiceAction.faceSearch);
    });
    test('optional name argument', () {
      expect(p('face search John Doe').argument, 'John Doe');
    });
  });

  group('investigations', () {
    test('investigations / cases phrasings', () {
      expect(p('open investigations').action, VoiceAction.investigations);
      expect(p('investigations').action, VoiceAction.investigations);
      expect(p('cases').action, VoiceAction.investigations);
      expect(p('my cases').action, VoiceAction.investigations);
      expect(p('case files').action, VoiceAction.investigations);
      expect(p('open investigations').argument, isNull);
    });
  });

  group('universal search', () {
    test('search / find / look up verbs', () {
      expect(p('search John Smith').action, VoiceAction.universalSearch);
      expect(p('search John Smith').argument, 'John Smith');
      expect(p('find Jane Doe').argument, 'Jane Doe');
      expect(p('look up acme corp').argument, 'acme corp');
      expect(p('lookup acme corp').action, VoiceAction.universalSearch);
      expect(p('who is tony stark').argument, 'tony stark');
    });
    test('bare text falls through to universal search', () {
      final i = p('Bruce Wayne');
      expect(i.action, VoiceAction.universalSearch);
      expect(i.argument, 'Bruce Wayne');
    });
    test('filler words are stripped from the argument', () {
      expect(p('search for the acme corp').argument, 'acme corp');
    });
  });

  group('robustness', () {
    test('empty / blank -> unknown', () {
      expect(p('').action, VoiceAction.unknown);
      expect(p('    ').action, VoiceAction.unknown);
    });
    test('case-insensitive', () {
      expect(p('OPEN LIVE CAMERA').action, VoiceAction.liveCamera);
      expect(p('SeArCh EmAiL x@y.com').action, VoiceAction.email);
    });
    test('extra whitespace collapsed', () {
      expect(p('   search    phone   123   ').action, VoiceAction.phone);
    });
    test('transcript is preserved verbatim', () {
      expect(p('  Find Jane  ').transcript, '  Find Jane  ');
    });
    test('verb with no following query keeps null argument', () {
      final i = p('search');
      expect(i.action, VoiceAction.universalSearch);
      expect(i.argument, isNull);
    });
  });

  group('VoiceIntent model', () {
    test('equality + hashCode', () {
      const a = VoiceIntent(
          action: VoiceAction.phone, argument: '1', transcript: 't');
      const b = VoiceIntent(
          action: VoiceAction.phone, argument: '1', transcript: 't');
      expect(a, b);
      expect(a.hashCode, b.hashCode);
    });
    test('hasArgument + actionLabel', () {
      expect(p('phone 123').hasArgument, isTrue);
      expect(p('camera').hasArgument, isFalse);
      expect(p('camera').actionLabel, 'LIVE CAMERA');
    });
  });
}
