import { API_BASE, getToken } from "@/lib/api";
import workletUrl from "@/lib/voiceWorklets.js?url";

/**
 * Live voice conversion client. It lives outside React so conversion keeps running
 * while the operator moves around KAI, and the app shell can show that it is on.
 *
 * Wire format (little endian), see backend app/voice/realtime.py:
 *   up:   u32 seq, u32 flags, f64 capture_ms, then Int16 PCM
 *   down: u32 seq, u32 flags (bit 0 = silence), f64 capture_ms, f32 proc_ms, f32 queue_ms, then Int16 PCM
 */
export type LiveState = "idle" | "starting" | "live" | "reconnecting" | "stopping" | "error";

export interface LiveSnapshot {
  state: LiveState;
  stage: string;
  /** Something the operator should know that doesn't stop conversion. */
  notice: string | null;
  error: string | null;
  profileId: string | null;
  sessionId: string | null;
  engine: string | null;
  device: string | null;
  sampleRate: number;
  blockMs: number;
  inputLevel: number;
  outputLevel: number;
  /** Capture to the moment the block reaches the output device. Measured; null until there is data. */
  latencyMs: number | null;
  latencyP95Ms: number | null;
  procMs: number | null;
  speaking: boolean;
  blocksSent: number;
  blocksReceived: number;
  blocksDroppedByServer: number;
  underruns: number;
  bufferMs: number;
  realtimeFactor: number | null;
  reconnects: number;
  micLost: boolean;
  outputSinkSupported: boolean;
  /** Set when this machine measured too slow for live use; conversion did not start. */
  tooSlow: { engine: string; device: string; procMs: number; blockMs: number } | null;
  /** True when running in the explicitly requested not-real-time mode. */
  delayed: boolean;
  /** Continuous, with long blocks: seconds behind rather than real time. */
  nearLive: boolean;
  /** How far behind the microphone the server queue currently is. */
  backlogMs: number;
}

export interface LiveSettings {
  inputDeviceId: string;
  outputDeviceId: string;
  inputGain: number;
  outputVolume: number;
  monitorConverted: boolean;
  monitorOriginal: boolean;
  monitorOriginalVolume: number;
  noiseSuppression: boolean;
  echoCancellation: boolean;
  virtualMic: boolean;
}

const INITIAL: LiveSnapshot = {
  state: "idle", stage: "", notice: null, error: null, profileId: null, sessionId: null, engine: null, device: null,
  sampleRate: 0, blockMs: 0, inputLevel: 0, outputLevel: 0, latencyMs: null, latencyP95Ms: null,
  procMs: null, speaking: false, blocksSent: 0, blocksReceived: 0, blocksDroppedByServer: 0,
  underruns: 0, bufferMs: 0, realtimeFactor: null, reconnects: 0, micLost: false,
  outputSinkSupported: "setSinkId" in AudioContext.prototype, tooSlow: null, delayed: false, nearLive: false, backlogMs: 0,
};

const SETTINGS_KEY = "kai.voice.live";
const DEFAULT_SETTINGS: LiveSettings = {
  inputDeviceId: "", outputDeviceId: "", inputGain: 1, outputVolume: 1, monitorConverted: true,
  monitorOriginal: false, monitorOriginalVolume: 0.5, noiseSuppression: true, echoCancellation: false,
  virtualMic: false,
};

function loadSettings(): LiveSettings {
  try {
    return { ...DEFAULT_SETTINGS, ...JSON.parse(localStorage.getItem(SETTINGS_KEY) ?? "{}") };
  } catch {
    return { ...DEFAULT_SETTINGS };
  }
}

const UP_HEADER = 16;
const DOWN_HEADER = 24;
const MAX_RECONNECT_DELAY_MS = 8000;

class LiveConversion {
  private snap: LiveSnapshot = { ...INITIAL };
  private listeners = new Set<() => void>();
  settings: LiveSettings = loadSettings();

  private ctx: AudioContext | null = null;
  private ws: WebSocket | null = null;
  private stream: MediaStream | null = null;
  private micNode: MediaStreamAudioSourceNode | null = null;
  private captureNode: AudioWorkletNode | null = null;
  private playbackNode: AudioWorkletNode | null = null;
  private inputGain: GainNode | null = null;
  private outputGain: GainNode | null = null;
  private originalGain: GainNode | null = null;
  private sink: GainNode | null = null;

  private wanted = false;
  private reconnectDelay = 500;
  private reconnectTimer: number | null = null;
  private pending: Float32Array[] = [];
  private pendingLen = 0;
  private blockSamples = 0;
  private seq = 0;
  private captureOffsetMs = 0;
  private latencies: number[] = [];
  private lastStatsSent = 0;
  private bufferSamples = 0;
  private underruns = 0;
  private lookaheadMs = 0;
  private delayed = false;
  private held: Float32Array[] = [];

  subscribe = (fn: () => void) => {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  };

  getSnapshot = () => this.snap;

  private set(patch: Partial<LiveSnapshot>) {
    this.snap = { ...this.snap, ...patch };
    this.listeners.forEach((fn) => fn());
  }

  updateSettings(patch: Partial<LiveSettings>) {
    const before = this.settings;
    this.settings = { ...before, ...patch };
    try {
      localStorage.setItem(SETTINGS_KEY, JSON.stringify(this.settings));
    } catch { /* settings just won't persist */ }
    this.applyGains();
    if (patch.outputDeviceId !== undefined && patch.outputDeviceId !== before.outputDeviceId) void this.applySink();
    const micChanged = (["inputDeviceId", "noiseSuppression", "echoCancellation"] as const)
      .some((k) => patch[k] !== undefined && patch[k] !== before[k]);
    if (micChanged && this.ctx) void this.acquireMic().catch((e) => this.onMicFailure(e));
    if (patch.virtualMic !== undefined && patch.virtualMic !== before.virtualMic) {
      this.sendJson({ type: "set_virtual_mic", enabled: patch.virtualMic });
    }
    this.listeners.forEach((fn) => fn());
  }

  async start(profileId: string, options?: { delayed?: boolean }) {
    if (this.wanted) return;
    this.wanted = true;
    this.delayed = !!options?.delayed;
    this.held = [];
    this.reconnectDelay = 500;
    this.set({ ...INITIAL, state: "starting", stage: "Connecting", profileId, delayed: this.delayed });
    this.connect();
  }

  async stop() {
    if (!this.wanted && this.snap.state === "idle") return;
    this.wanted = false;
    this.set({ state: "stopping", stage: "Stopping" });
    if (this.reconnectTimer !== null) window.clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
    if (this.ws?.readyState === WebSocket.OPEN) this.sendJson({ type: "stop" });
    this.ws?.close(1000);
    this.ws = null;
    await this.teardownAudio();
    this.set({ state: "idle", stage: "", notice: null, inputLevel: 0, outputLevel: 0, speaking: false });
  }

  setTarget(profileId: string) {
    this.set({ profileId });
    this.sendJson({ type: "set_target", profile_id: profileId });
  }

  private sendJson(msg: object) {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(msg));
  }

  private connect() {
    const scheme = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${scheme}://${location.host}${API_BASE}/voice/conversion/ws`);
    ws.binaryType = "arraybuffer";
    this.ws = ws;
    ws.onopen = () => {
      ws.send(JSON.stringify({
        type: "hello", token: getToken(), profile_id: this.snap.profileId, virtual_mic: this.settings.virtualMic,
        mode: this.delayed ? "delayed" : "live",
      }));
    };
    ws.onmessage = (e) => {
      if (this.ws !== ws) return;
      if (typeof e.data === "string") void this.onControl(JSON.parse(e.data));
      else this.onAudio(e.data as ArrayBuffer);
    };
    ws.onclose = () => {
      if (this.ws !== ws || !this.wanted) return;
      this.ws = null;
      this.set({ state: "reconnecting", stage: "Connection lost, reconnecting", reconnects: this.snap.reconnects + 1 });
      this.scheduleReconnect();
    };
  }

  private scheduleReconnect() {
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null;
      if (this.wanted) this.connect();
    }, this.reconnectDelay);
    this.reconnectDelay = Math.min(this.reconnectDelay * 2, MAX_RECONNECT_DELAY_MS);
  }

  private async onControl(msg: any) {
    switch (msg.type) {
      case "status":
        if (this.snap.state === "live") this.set({ notice: msg.stage ?? null });
        else this.set({ stage: msg.stage ?? this.snap.stage });
        break;
      case "ready":
        try {
          await this.onReady(msg);
        } catch (e) {
          this.onMicFailure(e);
        }
        break;
      case "target_changed":
        this.set({ stage: "", profileId: msg.profile_id });
        break;
      case "stats":
        this.set({
          blocksDroppedByServer: msg.dropped ?? 0,
          realtimeFactor: msg.realtime_factor ?? null,
          procMs: msg.proc_ms_avg ?? this.snap.procMs,
        });
        break;
      case "too_slow":
        this.wanted = false;
        this.ws?.close();
        this.ws = null;
        await this.teardownAudio();
        this.set({
          state: "idle", stage: "",
          tooSlow: { engine: msg.engine, device: msg.device, procMs: msg.proc_ms, blockMs: msg.block_ms },
        });
        break;
      case "error":
        await this.fail(msg.code ?? "conversion_failed", msg.message);
        break;
      case "stopped":
        break;
    }
  }

  /** Errors the operator has to fix do not retry; a dropped connection does. */
  private async fail(code: string, message?: string) {
    this.wanted = false;
    this.ws?.close();
    this.ws = null;
    await this.teardownAudio();
    this.set({ state: "error", stage: "", error: message ? `${code}: ${message}` : code, inputLevel: 0, outputLevel: 0 });
  }

  private onMicFailure(e: unknown) {
    if (this.abandoned) return;
    const name = (e as any)?.name ?? "";
    const text = name === "NotAllowedError"
      ? "Microphone permission was denied. Allow it in the browser and start again."
      : name === "NotFoundError" || name === "OverconstrainedError"
        ? "That microphone isn't available. Pick another one."
        : `Microphone failed: ${(e as any)?.message ?? e}`;
    void this.fail(text);
  }

  /** True once the operator has stopped: anything still in flight must undo itself. */
  private get abandoned() {
    return !this.wanted;
  }

  private async onReady(msg: any) {
    this.reconnectDelay = 500;
    this.blockSamples = msg.block_samples;
    this.lookaheadMs = msg.lookahead_ms ?? 0;
    this.seq = 0;
    this.pending = [];
    this.pendingLen = 0;
    this.latencies = [];
    this.set({
      nearLive: !!msg.near_live, sessionId: msg.session_id, engine: msg.engine, device: msg.device, sampleRate: msg.sample_rate,
      blockMs: (msg.block_samples / msg.sample_rate) * 1000, stage: "Opening the microphone",
    });
    if (this.ctx && this.ctx.sampleRate !== msg.sample_rate) await this.teardownAudio();
    if (!this.ctx) await this.setupAudio(msg.sample_rate, msg.block_samples);
    if (this.abandoned) return void (await this.teardownAudio());
    await this.acquireMic();
    if (this.abandoned) return void (await this.teardownAudio());
    // A block longer than half a second can't wait for a second one before playing: that would add
    // a whole block of delay. Play from the first, with a short lead-in to absorb jitter.
    const long = msg.block_samples / msg.sample_rate >= 0.5;
    this.playbackNode?.port.postMessage({
      flush: true,
      prebuffer: long ? msg.block_samples : Math.floor(msg.block_samples * 1.5),
      leadIn: long ? Math.floor(msg.sample_rate * 0.3) : 0,
    });
    this.set({ state: "live", stage: "", error: null });
  }

  private async setupAudio(rate: number, blockSamples: number) {
    // Running the whole graph at the engine's rate lets the browser do the high quality
    // resampling of the microphone and of the output.
    const ctx = new AudioContext({ sampleRate: rate, latencyHint: "interactive" });
    this.ctx = ctx;
    await ctx.audioWorklet.addModule(workletUrl);
    if (this.abandoned || this.ctx !== ctx) return;
    this.captureOffsetMs = performance.now() - ctx.currentTime * 1000;

    this.inputGain = ctx.createGain();
    this.outputGain = ctx.createGain();
    this.originalGain = ctx.createGain();
    this.sink = ctx.createGain();
    this.captureNode = new AudioWorkletNode(ctx, "kai-capture", { numberOfOutputs: 0 });
    this.playbackNode = new AudioWorkletNode(ctx, "kai-playback", {
      numberOfInputs: 0, outputChannelCount: [1], processorOptions: { prebuffer: Math.floor(blockSamples * 1.5) },
    });
    this.captureNode.port.onmessage = (e) => this.onCaptured(e.data);
    this.playbackNode.port.onmessage = (e) => this.onPlaybackStats(e.data);
    this.inputGain.connect(this.captureNode);
    this.inputGain.connect(this.originalGain);
    this.originalGain.connect(this.sink);
    this.playbackNode.connect(this.outputGain);
    this.outputGain.connect(this.sink);
    this.sink.connect(ctx.destination);
    this.applyGains();
    await this.applySink();
    await ctx.resume();
  }

  private async acquireMic() {
    const ctx = this.ctx;
    if (!ctx || !this.inputGain) return;
    const { inputDeviceId, noiseSuppression, echoCancellation } = this.settings;
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        deviceId: inputDeviceId ? { exact: inputDeviceId } : undefined,
        channelCount: 1, autoGainControl: false, noiseSuppression, echoCancellation,
      },
    });
    // Stopped while the permission prompt was open: release the microphone at once.
    if (this.abandoned || this.ctx !== ctx || !this.inputGain) {
      stream.getTracks().forEach((t) => t.stop());
      return;
    }
    this.micNode?.disconnect();
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = stream;
    this.micNode = ctx.createMediaStreamSource(stream);
    this.micNode.connect(this.inputGain);
    this.set({ micLost: false });
    stream.getAudioTracks()[0]?.addEventListener("ended", () => {
      if (this.stream !== stream || !this.wanted) return;
      this.set({ micLost: true, stage: "Microphone disconnected, waiting for it to return" });
      this.waitForMic();
    });
  }

  private waitForMic() {
    window.setTimeout(async () => {
      if (!this.wanted || !this.snap.micLost) return;
      try {
        await this.acquireMic();
        this.set({ stage: "" });
      } catch {
        this.waitForMic();
      }
    }, 1000);
  }

  private applyGains() {
    const s = this.settings;
    if (this.inputGain) this.inputGain.gain.value = s.inputGain;
    if (this.outputGain) this.outputGain.gain.value = s.monitorConverted ? s.outputVolume : 0;
    if (this.originalGain) this.originalGain.gain.value = s.monitorOriginal ? s.monitorOriginalVolume : 0;
  }

  private async applySink() {
    const ctx = this.ctx as any;
    if (ctx?.setSinkId) {
      try {
        await ctx.setSinkId(this.settings.outputDeviceId || "");
      } catch (e) {
        this.set({ notice: `Couldn't use that output device: ${(e as Error).message}` });
      }
    }
  }

  private onCaptured(data: any) {
    if (data.level !== undefined) {
      this.set({ inputLevel: data.level });
      return;
    }
    if (this.snap.state !== "live" || this.ws?.readyState !== WebSocket.OPEN) return;
    this.pending.push(data.samples);
    this.pendingLen += data.samples.length;
    while (this.pendingLen >= this.blockSamples) this.sendBlock(data.at);
  }

  private sendBlock(lastSampleAt: number) {
    const buffer = new ArrayBuffer(UP_HEADER + this.blockSamples * 2);
    const view = new DataView(buffer);
    const pcm = new Int16Array(buffer, UP_HEADER);
    let written = 0;
    while (written < this.blockSamples) {
      const head = this.pending[0];
      const take = Math.min(head.length, this.blockSamples - written);
      for (let i = 0; i < take; i++) {
        const v = Math.max(-1, Math.min(1, head[i]));
        pcm[written + i] = v < 0 ? v * 32768 : v * 32767;
      }
      written += take;
      if (take === head.length) this.pending.shift();
      else this.pending[0] = head.subarray(take);
    }
    this.pendingLen -= this.blockSamples;
    // The audio clock time of this block's newest sample, so measurement includes capture buffering.
    const leftoverMs = (this.pendingLen / (this.ctx?.sampleRate ?? 1)) * 1000;
    view.setUint32(0, this.seq++, true);
    view.setUint32(4, 0, true);
    view.setFloat64(8, lastSampleAt * 1000 + this.captureOffsetMs - leftoverMs, true);
    this.ws!.send(buffer);
    this.set({ blocksSent: this.snap.blocksSent + 1 });
  }

  private onAudio(buffer: ArrayBuffer) {
    if (buffer.byteLength < DOWN_HEADER || !this.ctx || !this.playbackNode) return;
    const view = new DataView(buffer);
    const flags = view.getUint32(4, true);
    const captureMs = view.getFloat64(8, true);
    const procMs = view.getFloat32(16, true);
    const backlogMs = view.getFloat32(20, true);
    const pcm = new Int16Array(buffer, DOWN_HEADER);
    const samples = new Float32Array(pcm.length);
    for (let i = 0; i < pcm.length; i++) samples[i] = pcm[i] / 32768;
    if (this.delayed) {
      // Far slower than real time: hold each phrase and play it whole, not as bursts between gaps.
      this.held.push(samples);
      if (flags & 1) {
        for (const part of this.held) this.playbackNode.port.postMessage({ samples: part }, [part.buffer]);
        this.held = [];
      }
    } else {
      this.playbackNode.port.postMessage({ samples }, [samples.buffer]);
    }

    const ctx = this.ctx;
    const outputS = (ctx.outputLatency ?? 0) + (ctx.baseLatency ?? 0);
    const queuedMs = (this.bufferSamples / ctx.sampleRate) * 1000;
    const durationMs = (pcm.length / ctx.sampleRate) * 1000;
    // Newest captured sample → when the end of this block leaves the speaker.
    // The engine also holds back a little audio to look ahead and crossfade, so the newest sample
    // of this output is that much older than the newest sample it was computed from.
    const latency = performance.now() - captureMs + queuedMs + durationMs + outputS * 1000 + this.lookaheadMs;
    const isSilence = (flags & 1) === 1;
    if (!isSilence) {
      this.latencies.push(latency);
      if (this.latencies.length > 200) this.latencies.shift();
    }
    const sorted = [...this.latencies].sort((a, b) => a - b);
    this.set({
      blocksReceived: this.snap.blocksReceived + 1,
      procMs,
      backlogMs,
      speaking: !isSilence,
      latencyMs: sorted.length ? sorted[Math.floor(sorted.length / 2)] : null,
      latencyP95Ms: sorted.length ? sorted[Math.floor(sorted.length * 0.95)] : null,
    });
    const now = performance.now();
    if (now - this.lastStatsSent > 2000 && sorted.length) {
      this.lastStatsSent = now;
      this.sendJson({
        type: "client_stats", latency_ms_p50: this.snap.latencyMs, latency_ms_p95: this.snap.latencyP95Ms,
        underruns: this.underruns,
      });
    }
  }

  private onPlaybackStats(data: any) {
    this.bufferSamples = data.fill ?? 0;
    this.underruns = data.underruns ?? 0;
    this.set({
      outputLevel: data.level ?? 0,
      underruns: this.underruns,
      bufferMs: this.ctx ? (this.bufferSamples / this.ctx.sampleRate) * 1000 : 0,
    });
  }

  private async teardownAudio() {
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
    this.micNode?.disconnect();
    this.micNode = null;
    this.captureNode?.port.close();
    this.playbackNode?.port.close();
    this.captureNode = null;
    this.playbackNode = null;
    this.inputGain = this.outputGain = this.originalGain = this.sink = null;
    const ctx = this.ctx;
    this.ctx = null;
    await ctx?.close().catch(() => undefined);
  }
}

export const liveConversion = new LiveConversion();
