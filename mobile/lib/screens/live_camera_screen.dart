import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:camera/camera.dart';
import 'package:flutter/material.dart';
import 'package:permission_handler/permission_handler.dart';

import '../models/live_face.dart';
import '../services/api_client.dart';
import '../theme/hacker_theme.dart';

/// C2 — Live camera face detection.
///
/// Opens the camera (front-facing by default), shows a live preview, and on a
/// throttled cadence captures a still frame and POSTs it to
/// /intelligence/face/frame for detection + hedged matching. Detected faces are
/// drawn as bounding boxes over the preview and listed in a bottom panel.
///
/// Guardrails: frames are EPHEMERAL — nothing is written to disk, and matches
/// are always presented as potential leads, never confirmed identity.
class LiveCameraScreen extends StatefulWidget {
  const LiveCameraScreen({super.key});

  @override
  State<LiveCameraScreen> createState() => _LiveCameraScreenState();
}

class _LiveCameraScreenState extends State<LiveCameraScreen>
    with WidgetsBindingObserver {
  static const _cadence = Duration(milliseconds: 1500);

  CameraController? _controller;
  List<CameraDescription> _cameras = const [];
  int _cameraIndex = 0;

  Timer? _timer;
  bool _inFlight = false;
  bool _running = false;
  bool _initializing = true;

  String? _permError;
  String? _notice; // transient server notice (e.g. engine offline)
  List<LiveFace> _faces = const [];
  Size? _imageSize; // pixel dims of the last captured JPEG

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _setup();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    final c = _controller;
    if (c == null || !c.value.isInitialized) return;
    if (state == AppLifecycleState.inactive ||
        state == AppLifecycleState.paused) {
      _stop();
    }
  }

  Future<void> _setup() async {
    setState(() {
      _initializing = true;
      _permError = null;
    });
    try {
      final status = await Permission.camera.request();
      if (!status.isGranted) {
        setState(() {
          _permError = status.isPermanentlyDenied
              ? 'Camera permission is permanently denied. Enable it in system settings.'
              : 'Camera permission denied. Grant access to use live detection.';
          _initializing = false;
        });
        return;
      }
      _cameras = await availableCameras();
      if (_cameras.isEmpty) {
        setState(() {
          _permError = 'No camera available on this device.';
          _initializing = false;
        });
        return;
      }
      // Prefer the front / user-facing camera.
      _cameraIndex = _cameras.indexWhere(
        (c) => c.lensDirection == CameraLensDirection.front,
      );
      if (_cameraIndex < 0) _cameraIndex = 0;
      await _initController();
    } catch (e) {
      setState(() {
        _permError = 'Could not start the camera.';
        _initializing = false;
      });
    }
  }

  Future<void> _initController() async {
    final old = _controller;
    _controller = null;
    await old?.dispose();

    final controller = CameraController(
      _cameras[_cameraIndex],
      ResolutionPreset.medium,
      enableAudio: false,
      imageFormatGroup: ImageFormatGroup.jpeg,
    );
    try {
      await controller.initialize();
      if (!mounted) {
        await controller.dispose();
        return;
      }
      setState(() {
        _controller = controller;
        _initializing = false;
        _faces = const [];
      });
    } catch (e) {
      setState(() {
        _permError = 'Could not initialise the camera.';
        _initializing = false;
      });
    }
  }

  bool get _hasMultipleCameras => _cameras.length > 1;

  Future<void> _switchCamera() async {
    if (!_hasMultipleCameras) return;
    final wasRunning = _running;
    _stop();
    setState(() => _initializing = true);
    _cameraIndex = (_cameraIndex + 1) % _cameras.length;
    await _initController();
    if (wasRunning) _start();
  }

  void _start() {
    final c = _controller;
    if (c == null || !c.value.isInitialized || _running) return;
    setState(() => _running = true);
    _timer = Timer.periodic(_cadence, (_) => _tick());
    _tick(); // kick off immediately
  }

  void _stop() {
    _timer?.cancel();
    _timer = null;
    if (mounted) {
      setState(() => _running = false);
    } else {
      _running = false;
    }
  }

  Future<void> _tick() async {
    if (_inFlight || !_running) return;
    final c = _controller;
    if (c == null || !c.value.isInitialized || c.value.isTakingPicture) return;

    _inFlight = true;
    if (mounted) setState(() {});
    try {
      final shot = await c.takePicture();
      final bytes = await shot.readAsBytes();
      // Frames are ephemeral: decode only to size the overlay, never persist.
      final size = await _decodeSize(bytes);

      final r = await ApiClient.instance.postImage(
        '/intelligence/face/frame',
        bytes,
        filename: 'frame.jpg',
        fields: {'match': 'true'},
      );

      if (!mounted) return;
      if (r.statusCode == 503) {
        setState(() {
          _notice = 'FACE ENGINE OFFLINE — preview only. (HTTP 503)';
          _faces = const [];
        });
      } else if (r.statusCode != 200) {
        setState(() => _notice = 'Frame rejected (HTTP ${r.statusCode}).');
      } else {
        final data = jsonDecode(r.body) as Map<String, dynamic>;
        final faces = ((data['faces'] as List?) ?? const [])
            .map((f) => LiveFace.fromJson(Map<String, dynamic>.from(f as Map)))
            .toList();
        setState(() {
          _faces = faces;
          _imageSize = size;
          _notice = null;
        });
      }
    } catch (e) {
      if (mounted) setState(() => _notice = 'Cannot reach backend. Check Settings.');
    } finally {
      _inFlight = false;
      if (mounted) setState(() {});
    }
  }

  Future<Size?> _decodeSize(Uint8List bytes) async {
    try {
      final codec = await ui.instantiateImageCodec(bytes);
      final frame = await codec.getNextFrame();
      final img = frame.image;
      final s = Size(img.width.toDouble(), img.height.toDouble());
      img.dispose();
      return s;
    } catch (_) {
      return null;
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _timer?.cancel();
    _controller?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      appBar: AppBar(
        title: const Text('Live Detection'),
        actions: [
          if (_hasMultipleCameras)
            IconButton(
              tooltip: 'Switch camera',
              icon: const Icon(Icons.cameraswitch_outlined),
              onPressed: _initializing ? null : _switchCamera,
            ),
        ],
      ),
      body: _buildBody(),
      bottomNavigationBar: _buildControlBar(),
    );
  }

  Widget _buildBody() {
    if (_permError != null) return _buildPermError();
    if (_initializing || _controller == null) {
      return const Center(
        child: CircularProgressIndicator(color: KaiColors.accent),
      );
    }
    final c = _controller!;
    return Column(
      children: [
        Expanded(child: _buildPreview(c)),
        _buildFacePanel(),
      ],
    );
  }

  Widget _buildPermError() {
    return Padding(
      padding: const EdgeInsets.all(24),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          const Icon(Icons.no_photography_outlined,
              color: KaiColors.danger, size: 40),
          const SizedBox(height: 12),
          Text(
            _permError!,
            textAlign: TextAlign.center,
            style: const TextStyle(color: KaiColors.ink),
          ),
          const SizedBox(height: 16),
          Wrap(
            spacing: 8,
            alignment: WrapAlignment.center,
            children: [
              OutlinedButton(onPressed: _setup, child: const Text('Retry')),
              FilledButton(
                style: FilledButton.styleFrom(
                    backgroundColor: KaiColors.accent,
                    foregroundColor: Colors.black),
                onPressed: openAppSettings,
                child: const Text('Open settings'),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildPreview(CameraController c) {
    // Draw the preview and overlay in the captured image's pixel coordinate
    // space, then cover-fit the whole thing to the available box so bbox
    // coordinates (image pixels) map 1:1 to the painter.
    final previewSize = c.value.previewSize;
    // previewSize is sensor-oriented (landscape); fall back to it until a
    // real frame gives us exact JPEG dims.
    final space = _imageSize ??
        (previewSize != null
            ? Size(previewSize.height, previewSize.width)
            : const Size(720, 1280));

    return LayoutBuilder(
      builder: (context, constraints) {
        return ClipRect(
          child: Stack(
            fit: StackFit.expand,
            children: [
              FittedBox(
                fit: BoxFit.cover,
                clipBehavior: Clip.hardEdge,
                child: SizedBox(
                  width: space.width,
                  height: space.height,
                  child: Stack(
                    children: [
                      Positioned.fill(child: CameraPreview(c)),
                      Positioned.fill(
                        child: CustomPaint(
                          painter: _FaceBoxPainter(_faces, space),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
              // In-flight / scanning indicator.
              Positioned(
                top: 10,
                left: 10,
                child: _StatusPill(
                  running: _running,
                  scanning: _inFlight,
                ),
              ),
              if (_notice != null)
                Positioned(
                  top: 10,
                  right: 10,
                  left: 90,
                  child: _NoticeBanner(_notice!),
                ),
            ],
          ),
        );
      },
    );
  }

  Widget _buildFacePanel() {
    return Container(
      constraints: const BoxConstraints(maxHeight: 190, minHeight: 72),
      width: double.infinity,
      decoration: const BoxDecoration(
        color: KaiColors.panel,
        border: Border(top: BorderSide(color: KaiColors.line)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(12, 10, 12, 6),
            child: Text(
              _faces.isEmpty
                  ? 'NO FACES IN FRAME'
                  : '${_faces.length} FACE${_faces.length == 1 ? '' : 'S'} — potential leads, not confirmed identity',
              style: const TextStyle(
                  color: KaiColors.muted, fontSize: 11, letterSpacing: 1),
            ),
          ),
          Flexible(
            child: _faces.isEmpty
                ? const SizedBox.shrink()
                : ListView.separated(
                    padding: const EdgeInsets.fromLTRB(12, 0, 12, 10),
                    itemCount: _faces.length,
                    separatorBuilder: (_, _) => const SizedBox(height: 6),
                    itemBuilder: (_, i) => _FaceRow(face: _faces[i], index: i),
                  ),
          ),
        ],
      ),
    );
  }

  Widget _buildControlBar() {
    if (_permError != null) return const SizedBox.shrink();
    return SafeArea(
      top: false,
      child: Container(
        padding: const EdgeInsets.fromLTRB(16, 10, 16, 10),
        color: KaiColors.bg,
        child: Row(
          children: [
            Expanded(
              child: FilledButton.icon(
                icon: Icon(_running ? Icons.stop : Icons.play_arrow),
                label: Text(_running ? 'STOP' : 'START'),
                style: FilledButton.styleFrom(
                  backgroundColor:
                      _running ? KaiColors.danger : KaiColors.accent,
                  foregroundColor: Colors.black,
                ),
                onPressed: (_initializing || _controller == null)
                    ? null
                    : () => _running ? _stop() : _start(),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// Draws a coloured bounding box + label per detected face. Coordinates are in
/// the captured image's pixel space, which is also this painter's canvas size.
class _FaceBoxPainter extends CustomPainter {
  final List<LiveFace> faces;
  final Size imageSize;
  _FaceBoxPainter(this.faces, this.imageSize);

  @override
  void paint(Canvas canvas, Size size) {
    // Scale from image pixel space to the actual canvas size (they match when
    // the SizedBox equals imageSize, but guard against rounding).
    final sx = size.width / imageSize.width;
    final sy = size.height / imageSize.height;

    for (final f in faces) {
      final color = KaiColors.band(f.match?.band);
      final rect = Rect.fromLTRB(
        f.x1 * sx,
        f.y1 * sy,
        f.x2 * sx,
        f.y2 * sy,
      );
      final stroke = Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 2.5
        ..color = color;
      canvas.drawRRect(
        RRect.fromRectAndRadius(rect, const Radius.circular(4)),
        stroke,
      );

      final label = _labelFor(f);
      if (label.isEmpty) continue;
      final tp = TextPainter(
        text: TextSpan(
          text: ' $label ',
          style: const TextStyle(
            color: Colors.black,
            fontSize: 12,
            fontWeight: FontWeight.w600,
          ),
        ),
        textDirection: TextDirection.ltr,
      )..layout(maxWidth: size.width);
      final bgTop = (rect.top - tp.height - 2).clamp(0.0, size.height);
      final bg = Rect.fromLTWH(rect.left, bgTop, tp.width, tp.height);
      canvas.drawRect(bg, Paint()..color = color);
      tp.paint(canvas, Offset(rect.left, bgTop));
    }
  }

  String _labelFor(LiveFace f) {
    final parts = <String>[];
    if (f.demographics.isNotEmpty) parts.add(f.demographics);
    final m = f.match;
    if (m != null && m.similarityPct != null) {
      final name = m.names.isNotEmpty ? m.names.first : m.pageTitle;
      final pct = '${m.similarityPct!.toStringAsFixed(0)}%';
      parts.add(name != null && name.isNotEmpty ? '$pct $name' : pct);
    }
    return parts.join('  ');
  }

  @override
  bool shouldRepaint(covariant _FaceBoxPainter old) =>
      old.faces != faces || old.imageSize != imageSize;
}

/// One row in the bottom detected-faces panel.
class _FaceRow extends StatelessWidget {
  final LiveFace face;
  final int index;
  const _FaceRow({required this.face, required this.index});

  @override
  Widget build(BuildContext context) {
    final color = KaiColors.band(face.match?.band);
    final m = face.match;
    final hasMatch = m != null && m.similarityPct != null;
    final name = hasMatch
        ? (m.names.isNotEmpty ? m.names.first : (m.pageTitle ?? 'Unknown'))
        : null;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
      decoration: BoxDecoration(
        color: KaiColors.panel2,
        border: Border.all(color: KaiColors.line),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        children: [
          Container(
            width: 10,
            height: 10,
            decoration: BoxDecoration(color: color, shape: BoxShape.circle),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Text(
                      'FACE ${index + 1}',
                      style: const TextStyle(
                          color: KaiColors.ink,
                          fontSize: 12,
                          fontWeight: FontWeight.bold),
                    ),
                    if (face.demographics.isNotEmpty) ...[
                      const SizedBox(width: 8),
                      Text(face.demographics,
                          style: const TextStyle(
                              color: KaiColors.muted, fontSize: 11)),
                    ],
                  ],
                ),
                const SizedBox(height: 2),
                if (hasMatch)
                  Text(
                    '${m.similarityPct!.toStringAsFixed(0)}% · ${KaiColors.bandLabel(m.band)}${name != null && name.isNotEmpty ? ' · $name' : ''}',
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(color: color, fontSize: 11),
                  )
                else
                  const Text('no gallery match',
                      style: TextStyle(color: KaiColors.muted, fontSize: 11)),
              ],
            ),
          ),
          Text(
            'q ${(face.quality * 100).toStringAsFixed(0)}',
            style: const TextStyle(color: KaiColors.muted, fontSize: 10),
          ),
        ],
      ),
    );
  }
}

/// Small running/scanning indicator pill shown over the preview.
class _StatusPill extends StatelessWidget {
  final bool running;
  final bool scanning;
  const _StatusPill({required this.running, required this.scanning});

  @override
  Widget build(BuildContext context) {
    final Color dot;
    final String label;
    if (!running) {
      dot = KaiColors.muted;
      label = 'PAUSED';
    } else if (scanning) {
      dot = KaiColors.warn;
      label = 'ANALYZING…';
    } else {
      dot = KaiColors.accent;
      label = 'LIVE';
    }
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: Colors.black.withValues(alpha: 0.55),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: KaiColors.line),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 8,
            height: 8,
            decoration: BoxDecoration(color: dot, shape: BoxShape.circle),
          ),
          const SizedBox(width: 6),
          Text(label,
              style: TextStyle(color: dot, fontSize: 11, letterSpacing: 1)),
        ],
      ),
    );
  }
}

class _NoticeBanner extends StatelessWidget {
  final String text;
  const _NoticeBanner(this.text);

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(
        color: Colors.black.withValues(alpha: 0.6),
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: KaiColors.warn),
      ),
      child: Text(
        text,
        style: const TextStyle(color: KaiColors.warn, fontSize: 11),
      ),
    );
  }
}
