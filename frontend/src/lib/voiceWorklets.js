// AudioWorklet processors for live voice conversion. These run on the audio thread.

// Forwards microphone samples to the main thread and reports the input level.
class KaiCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.peak = 0;
    this.count = 0;
  }
  process(inputs) {
    const channel = inputs[0]?.[0];
    if (channel) {
      this.port.postMessage({ samples: channel.slice(0), at: currentTime + channel.length / sampleRate });
      for (let i = 0; i < channel.length; i++) this.peak = Math.max(this.peak, Math.abs(channel[i]));
      this.count += channel.length;
      if (this.count >= sampleRate / 20) {
        this.port.postMessage({ level: this.peak });
        this.peak = 0;
        this.count = 0;
      }
    }
    return true;
  }
}
registerProcessor("kai-capture", KaiCapture);

// Jitter buffer for converted audio. Waits for `prebuffer` samples before playing, and
// goes back to waiting after an underrun, so a late block costs one audible gap instead
// of a stream of stutters.
class KaiPlayback extends AudioWorkletProcessor {
  constructor(options) {
    super();
    this.capacity = Math.floor(sampleRate * 10);
    this.ring = new Float32Array(this.capacity);
    this.read = 0;
    this.write = 0;
    this.fill = 0;
    this.prebuffer = options.processorOptions?.prebuffer ?? Math.floor(sampleRate * 0.1);
    // Silence played before audio resumes, to absorb jitter when blocks are long.
    this.leadIn = options.processorOptions?.leadIn ?? 0;
    this.leadLeft = 0;
    this.playing = false;
    this.underruns = 0;
    this.dropped = 0;
    this.peak = 0;
    this.count = 0;
    this.port.onmessage = (e) => {
      if (e.data.samples) this.push(e.data.samples);
      if (e.data.prebuffer) this.prebuffer = e.data.prebuffer;
      if (e.data.leadIn !== undefined) this.leadIn = e.data.leadIn;
      if (e.data.flush) {
        this.read = this.write = this.fill = 0;
        this.playing = false;
      }
    };
  }
  push(samples) {
    for (let i = 0; i < samples.length; i++) {
      if (this.fill === this.capacity) {
        this.read = (this.read + 1) % this.capacity; // never let latency grow without bound
        this.fill--;
        this.dropped++;
      }
      this.ring[this.write] = samples[i];
      this.write = (this.write + 1) % this.capacity;
      this.fill++;
    }
  }
  process(_inputs, outputs) {
    const out = outputs[0][0];
    if (!out) return true;
    if (!this.playing && this.fill >= this.prebuffer) {
      this.playing = true;
      this.leadLeft = this.leadIn;
    }
    let underran = false;
    for (let i = 0; i < out.length; i++) {
      if (this.leadLeft > 0) {
        out[i] = 0;
        this.leadLeft--;
      } else if (this.playing && this.fill > 0) {
        const v = this.ring[this.read];
        out[i] = v;
        this.peak = Math.max(this.peak, Math.abs(v));
        this.read = (this.read + 1) % this.capacity;
        this.fill--;
      } else {
        out[i] = 0;
        if (this.playing) underran = true;
      }
    }
    if (underran) {
      this.playing = false;
      this.underruns++;
    }
    this.count += out.length;
    if (this.count >= sampleRate / 20) {
      this.port.postMessage({ level: this.peak, fill: this.fill + this.leadLeft, underruns: this.underruns, dropped: this.dropped });
      this.peak = 0;
      this.count = 0;
    }
    return true;
  }
}
registerProcessor("kai-playback", KaiPlayback);
