/**
 * AudioWorkletProcessor — ring-buffer playback for 24 kHz PCM mono.
 *
 * This module is loaded into the AudioWorkletGlobalScope via
 * `audioContext.audioWorklet.addModule(url)`. It is *not* a normal browser
 * module — `window`, `document`, etc. are not available here. Only the
 * AudioWorkletGlobalScope APIs (`sampleRate`, `registerProcessor`,
 * `AudioWorkletProcessor`, `currentFrame`, `currentTime`).
 *
 * Protocol — main thread → worklet:
 *   { cmd: "push",   samples: Int16Array | Float32Array }
 *   { cmd: "pause"  }
 *   { cmd: "resume" }
 *   { cmd: "flush"  }
 *   { cmd: "seek",   offsetMs: number }    // best-effort, relative to recent pushes
 *
 * Worklet → main thread:
 *   { type: "progress", currentMs: number }  // every ~100 ms
 *
 * Status (A2): wired but inactive. The current `useTtsPlayback` hook still
 * uses `speechSynthesis` under the hood — see the hook for the rationale.
 * This worklet is ready for the backend TTS pipeline to start streaming
 * 24 kHz PCM frames.
 */

/// <reference lib="webworker" />

declare const sampleRate: number;
declare const currentFrame: number;
declare function registerProcessor(
  name: string,
  ctor: new (options?: AudioWorkletNodeOptions) => AudioWorkletProcessor,
): void;

declare class AudioWorkletProcessor {
  readonly port: MessagePort;
  constructor(options?: AudioWorkletNodeOptions);
  process(
    inputs: Float32Array[][],
    outputs: Float32Array[][],
    parameters: Record<string, Float32Array>,
  ): boolean;
}

type PushMsg = { cmd: 'push'; samples: Int16Array | Float32Array };
type PauseMsg = { cmd: 'pause' };
type ResumeMsg = { cmd: 'resume' };
type FlushMsg = { cmd: 'flush' };
type SeekMsg = { cmd: 'seek'; offsetMs: number };
type InMsg = PushMsg | PauseMsg | ResumeMsg | FlushMsg | SeekMsg;

const SOURCE_SAMPLE_RATE = 24000; // Gemini Live native audio is 24 kHz mono
const RING_CAPACITY = 1024 * 1024; // ~1M samples ≈ 43.7 s at 24 kHz ≈ 4 MB Float32

class PlaybackProcessor extends AudioWorkletProcessor {
  private ring: Float32Array;
  private readIndex = 0;
  private writeIndex = 0;
  private paused = false;
  /** Total samples drained since instantiation — drives progress reporting. */
  private samplesDrained = 0;
  /** Last `samplesDrained` value we reported, in worklet sample-rate frames. */
  private lastReportedFrame = 0;
  /** SRC ratio: target context rate / source rate (e.g. 48000/24000 = 2). */
  private readonly upsampleRatio: number;
  private fractional = 0;

  constructor() {
    super();
    this.ring = new Float32Array(RING_CAPACITY);
    this.upsampleRatio = sampleRate / SOURCE_SAMPLE_RATE;
    this.port.onmessage = (e: MessageEvent<InMsg>) => this.onMessage(e.data);
  }

  private onMessage(msg: InMsg) {
    switch (msg.cmd) {
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
        this.readIndex = this.writeIndex;
        this.fractional = 0;
        break;
      case 'seek': {
        // Best-effort: rewind/advance readIndex by `offsetMs` worth of source samples.
        const deltaSamples = Math.round((msg.offsetMs / 1000) * SOURCE_SAMPLE_RATE);
        const available = this.writeIndex - this.readIndex;
        const target = this.readIndex + deltaSamples;
        if (target < this.writeIndex - available) {
          // Beyond what we still have buffered — clamp to oldest available.
          this.readIndex = this.writeIndex - available;
        } else if (target > this.writeIndex) {
          this.readIndex = this.writeIndex;
        } else {
          this.readIndex = Math.max(0, target);
        }
        this.fractional = 0;
        break;
      }
    }
  }

  private handlePush(samples: Int16Array | Float32Array) {
    const cap = this.ring.length;
    let i = 0;
    const len = samples.length;
    if (samples instanceof Int16Array) {
      while (i < len) {
        this.ring[this.writeIndex % cap] = samples[i]! / 32768;
        this.writeIndex++;
        i++;
      }
    } else {
      while (i < len) {
        this.ring[this.writeIndex % cap] = samples[i]!;
        this.writeIndex++;
        i++;
      }
    }
    // If write got too far ahead, advance read to keep at most `cap` samples.
    const lag = this.writeIndex - this.readIndex;
    if (lag > cap) {
      this.readIndex = this.writeIndex - cap;
    }
  }

  override process(_inputs: Float32Array[][], outputs: Float32Array[][]): boolean {
    const out = outputs[0]?.[0];
    if (!out) return true;
    const frames = out.length;
    const cap = this.ring.length;

    if (this.paused) {
      out.fill(0);
      return true;
    }

    // Linear-interpolate from source rate to context rate.
    const step = 1 / this.upsampleRatio; // source samples consumed per output frame
    for (let i = 0; i < frames; i++) {
      const available = this.writeIndex - this.readIndex;
      if (available <= 0) {
        out[i] = 0; // underrun → silence
        continue;
      }
      const idx = this.readIndex % cap;
      const sample = this.ring[idx] ?? 0;
      out[i] = sample;
      this.fractional += step;
      while (this.fractional >= 1 && this.readIndex < this.writeIndex) {
        this.readIndex++;
        this.samplesDrained++;
        this.fractional -= 1;
      }
    }

    // Emit progress every ~100 ms.
    const framesSinceReport = currentFrame - this.lastReportedFrame;
    if (framesSinceReport >= sampleRate / 10) {
      this.lastReportedFrame = currentFrame;
      const currentMs = (this.samplesDrained / SOURCE_SAMPLE_RATE) * 1000;
      this.port.postMessage({ type: 'progress', currentMs });
    }

    return true;
  }
}

registerProcessor('playback-processor', PlaybackProcessor);

export {};
