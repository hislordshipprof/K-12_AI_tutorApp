/**
 * AudioWorkletProcessor — microphone capture, downsampled to 16 kHz PCM mono.
 *
 * Reads `inputs[0][0]` (the mic Float32 stream at the AudioContext rate,
 * typically 44.1 or 48 kHz) and decimates to 16 kHz using a simple boxcar
 * average. Emits Int16 PCM in ~100 ms chunks via:
 *
 *   { type: "pcm16", samples: Int16Array }
 *
 * Status (A2): defined; consumed by A3's `useGeminiLive` hook.
 */

/// <reference lib="webworker" />

declare const sampleRate: number;
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

const TARGET_SAMPLE_RATE = 16000;
const CHUNK_MS = 100;
const TARGET_SAMPLES_PER_CHUNK = Math.round((TARGET_SAMPLE_RATE * CHUNK_MS) / 1000); // 1600

class CaptureProcessor extends AudioWorkletProcessor {
  private readonly decimation: number;
  private accumulator = 0;
  private accumulatedCount = 0;
  private chunk: Int16Array;
  private chunkOffset = 0;

  constructor() {
    super();
    // e.g. sampleRate=48000 → decimation=3
    this.decimation = Math.max(1, Math.round(sampleRate / TARGET_SAMPLE_RATE));
    this.chunk = new Int16Array(TARGET_SAMPLES_PER_CHUNK);
  }

  override process(inputs: Float32Array[][]): boolean {
    const input = inputs[0]?.[0];
    if (!input || input.length === 0) return true;

    for (let i = 0; i < input.length; i++) {
      this.accumulator += input[i]!;
      this.accumulatedCount++;
      if (this.accumulatedCount >= this.decimation) {
        const avg = this.accumulator / this.accumulatedCount;
        // Clamp + scale to Int16.
        const clamped = Math.max(-1, Math.min(1, avg));
        this.chunk[this.chunkOffset++] = (clamped * 32767) | 0;
        this.accumulator = 0;
        this.accumulatedCount = 0;

        if (this.chunkOffset >= this.chunk.length) {
          // Transfer ownership to the main thread to avoid copy cost.
          const out = this.chunk;
          this.chunk = new Int16Array(TARGET_SAMPLES_PER_CHUNK);
          this.chunkOffset = 0;
          this.port.postMessage({ type: 'pcm16', samples: out }, [out.buffer]);
        }
      }
    }
    return true;
  }
}

registerProcessor('capture-processor', CaptureProcessor);

export {};
