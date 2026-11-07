import 'package:flutter/material.dart';

import '../services/api_client.dart';
import '../theme/hacker_theme.dart';

const _agentLabels = {
  'shell_network': 'Shell & Network',
  'web_research': 'Web Research',
  'map_geo': 'Maps & Geo',
  'people_identity': 'People & Identity',
  'investigations_files': 'Investigations & Files',
  'general': 'General',
};

class _ChatMsg {
  _ChatMsg({required this.fromUser, this.text = ''});

  final bool fromUser;
  String text;
  String? agent;
  String? reason;
  List<String> toolLines = [];
  bool error = false;
}

/// KAI chat — streams agent responses over SSE with auto-approved tools.
class ChatScreen extends StatefulWidget {
  const ChatScreen({super.key});

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> {
  String? _conversationId;
  final List<_ChatMsg> _messages = [];
  final TextEditingController _c = TextEditingController();
  final ScrollController _scroll = ScrollController();
  bool _streaming = false;

  @override
  void dispose() {
    _c.dispose();
    _scroll.dispose();
    super.dispose();
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted || !_scroll.hasClients) return;
      _scroll.jumpTo(_scroll.position.maxScrollExtent);
    });
  }

  Future<void> _send() async {
    final input = _c.text.trim();
    if (input.isEmpty || _streaming) return;
    setState(() => _streaming = true);
    try {
      _conversationId ??= await ApiClient.instance.createConversation();
      if (!mounted) return;
      if (_conversationId == null) {
        setState(() {
          _messages.add(
            _ChatMsg(fromUser: false, text: 'Could not start a conversation.')
              ..error = true,
          );
        });
        _scrollToBottom();
        return;
      }
      final reply = _ChatMsg(fromUser: false);
      setState(() {
        _messages.add(_ChatMsg(fromUser: true, text: input));
        _messages.add(reply);
        _c.clear();
      });
      _scrollToBottom();
      await ApiClient.instance.streamMessage(
        _conversationId!,
        input,
        onEvent: (event, data) {
          if (!mounted) return;
          setState(() => _apply(reply, event, data));
          _scrollToBottom();
        },
      );
    } catch (e) {
      if (mounted) {
        setState(() {
          _messages.add(
            _ChatMsg(fromUser: false, text: 'Error: $e')..error = true,
          );
        });
      }
    } finally {
      if (mounted) setState(() => _streaming = false);
    }
  }

  void _apply(_ChatMsg m, String event, Map<String, dynamic> data) {
    switch (event) {
      case 'token':
        final t = data['text'];
        if (t is String) m.text += t;
        break;
      case 'agent_selected':
        if (m.agent == null) {
          m.agent = data['agent']?.toString();
          m.reason = data['reason']?.toString();
        }
        break;
      case 'tool_call':
        m.toolLines.add('▸ running ${data['operation']}');
        break;
      case 'tool_result':
        if (m.toolLines.isNotEmpty) {
          m.toolLines[m.toolLines.length - 1] += ' ✓';
        }
        break;
      case 'message':
      case 'final':
        final a = data['answer'];
        if (a is String && a.isNotEmpty) m.text = a;
        break;
      case 'error':
        m.error = true;
        m.text = (data['message'] ?? 'error').toString();
        break;
    }
  }

  Widget _bubble(_ChatMsg m, bool isLast) {
    final waiting = !m.fromUser && isLast && _streaming && m.text.isEmpty;
    final badge = m.agent == null
        ? null
        : '${_agentLabels[m.agent] ?? m.agent}'
              '${(m.reason ?? '').isEmpty ? '' : ' · ${m.reason}'}';
    return Align(
      alignment: m.fromUser ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        margin: const EdgeInsets.symmetric(vertical: 4),
        padding: const EdgeInsets.all(10),
        constraints: BoxConstraints(
          maxWidth: MediaQuery.of(context).size.width * 0.85,
        ),
        decoration: BoxDecoration(
          color: m.fromUser ? KaiColors.panel2 : KaiColors.panel,
          border: Border.all(color: KaiColors.line),
          borderRadius: BorderRadius.circular(8),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            if (badge != null)
              Container(
                margin: const EdgeInsets.only(bottom: 6),
                padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                decoration: BoxDecoration(
                  color: KaiColors.hudDim,
                  borderRadius: BorderRadius.circular(10),
                ),
                child: Text(
                  badge,
                  style: const TextStyle(color: KaiColors.hud, fontSize: 11),
                ),
              ),
            for (final l in m.toolLines)
              Text(
                l,
                style: const TextStyle(
                  color: KaiColors.muted,
                  fontSize: 11,
                  fontFamily: 'monospace',
                ),
              ),
            if (m.toolLines.isNotEmpty && m.text.isNotEmpty)
              const SizedBox(height: 6),
            if (waiting)
              const Text(
                'thinking…',
                style: TextStyle(color: KaiColors.muted, fontSize: 12),
              )
            else if (m.text.isNotEmpty)
              SelectableText(
                m.text,
                style: TextStyle(
                  color: m.error ? KaiColors.danger : KaiColors.ink,
                ),
              ),
          ],
        ),
      ),
    );
  }

  Widget _inputBar() {
    return SafeArea(
      top: false,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(12, 6, 4, 8),
        child: Row(
          children: [
            Expanded(
              child: TextField(
                controller: _c,
                style: const TextStyle(color: KaiColors.ink),
                textInputAction: TextInputAction.send,
                onSubmitted: (_) => _send(),
                decoration: const InputDecoration(
                  hintText: 'Ask KAI…',
                  filled: true,
                  fillColor: KaiColors.panel,
                ),
              ),
            ),
            IconButton(
              icon: const Icon(Icons.send),
              color: KaiColors.hud,
              onPressed: _streaming ? null : _send,
            ),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('KAI Chat')),
      body: Column(
        children: [
          Expanded(
            child: ListView.builder(
              controller: _scroll,
              padding: const EdgeInsets.all(12),
              itemCount: _messages.length,
              itemBuilder: (_, i) =>
                  _bubble(_messages[i], i == _messages.length - 1),
            ),
          ),
          _inputBar(),
        ],
      ),
    );
  }
}
