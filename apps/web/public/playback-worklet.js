/**
 * AudioWorkletProcessor — ring-buffer playback for 24 kHz PCM mono.
 *
 * Served as a static asset from `/public` so `AudioWorklet.addModule()`
 * loads it verbatim — an AudioWorklet module must be plain browser JS, and
 * bundling a `.ts` worklet via `new URL(..., import.meta.url)` does not
 * reliably resolve under Turbopack (it failed with "Unable to load a
 * worklet's module"). Keep this file plain JS — no TypeScript, no imports.
 * The TypeScript twin in `src/audio/playback-worklet.ts` is kept only as
 * documentation of the protocol; this file is the one that actually runs.
 *
 * Protocol — main thread -> worklet:
 *   { cmd: "push",   samples: Int16Array | Float32Array }
 *   { cmd: "pause"  }
 *   { cmd: "resume" }
 *   { cmd: "flush"  }   // barge-in: drop everything still queued
 *
 * Gemini Live native audio is 24 kHz mono; we linear-interpolate up to the
 * AudioContext rate (typically 44.1/48 kHz) inside `process`.
 */

const SOURCE_SAMPLE_RATE = 24000;
const RING_CAPACITY = 1024 * 1024; // ~43 s at 24 kHz

class PlaybackProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.ring = new Float32Array(RING_CAPACITY);
    this.readIndex = 0;
    this.writeIndex = 0;
    this.paused = false;
    // SRC ratio: context rate / source rate (e.g. 48000/24000 = 2).
    this.upsampleRatio = sampleRate / SOURCE_SAMPLE_RATE;
    this.fractional = 0;
    this.port.onmessage = (e) => this.onMessage(e.data);
  }

  onMessage(msg) {
    switch (msg && msg.cmd) {
      case 'push':
        this.handlePush(msg.samples);
        break;
      case 'pause':
        this.paused = true;
        break;
      case 'resume':
        this.paused = false;
        break;
      case 'flush':
        // Barge-in — drop the queue so Aria stops talking immediately.
        this.readIndex = this.writeIndex;
        this.fractional = 0;
        break;
      default:
        break;
    }
  }

  handlePush(samples) {
    if (!samples || samples.length === 0) return;
    const cap = this.ring.length;
    const len = samples.length;
    const isInt16 = samples instanceof Int16Array;
    for (let i = 0; i < len; i++) {
      this.ring[this.writeIndex % cap] = isInt16 ? samples[i] / 32768 : samples[i];
      this.writeIndex++;
    }
    // If write got too far ahead, advance read to keep at most `cap` samples.
    if (this.writeIndex - this.readIndex > cap) {
      this.readIndex = this.writeIndex - cap;
    }
  }

  process(_inputs, outputs) {
    const out = outputs[0] && outputs[0][0];
    if (!out) return true;
    const frames = out.length;
    const cap = this.ring.length;

    if (this.paused) {
      out.fill(0);
      return true;
    }

    // source samples consumed per output frame
    const step = 1 / this.upsampleRatio;
    for (let i = 0; i < frames; i++) {
      if (this.writeIndex - this.readIndex <= 0) {
        out[i] = 0; // underrun -> silence
        continue;
      }
      out[i] = this.ring[this.readIndex % cap] || 0;
      this.fractional += step;
      while (this.fractional >= 1 && this.readIndex < this.writeIndex) {
        this.readIndex++;
        this.fractional -= 1;
      }
    }
    return true;
  }
}

registerProcessor('playback-processor', PlaybackProcessor);
