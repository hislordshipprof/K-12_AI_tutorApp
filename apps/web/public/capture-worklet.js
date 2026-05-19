/**
 * AudioWorkletProcessor — microphone capture, downsampled to 16 kHz PCM mono.
 *
 * Served as a static asset from `/public` so `AudioWorklet.addModule()`
 * loads it verbatim — an AudioWorklet module must be plain browser JS, and
 * bundling a `.ts` worklet via `new URL(..., import.meta.url)` does not
 * reliably resolve under Turbopack (it failed with "Unable to load a
 * worklet's module"). Keep this file plain JS — no TypeScript, no imports.
 *
 * Reads `inputs[0][0]` (the mic Float32 stream at the AudioContext rate,
 * typically 44.1 or 48 kHz) and decimates to 16 kHz with a boxcar average.
 * Emits Int16 PCM in ~100 ms chunks via: { type: "pcm16", samples }.
 */

const TARGET_SAMPLE_RATE = 16000;
const CHUNK_MS = 100;
const TARGET_SAMPLES_PER_CHUNK = Math.round(
  (TARGET_SAMPLE_RATE * CHUNK_MS) / 1000,
); // 1600

class CaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    // e.g. sampleRate=48000 → decimation=3. `sampleRate` is an
    // AudioWorkletGlobalScope global.
    this.decimation = Math.max(1, Math.round(sampleRate / TARGET_SAMPLE_RATE));
    this.accumulator = 0;
    this.accumulatedCount = 0;
    this.chunk = new Int16Array(TARGET_SAMPLES_PER_CHUNK);
    this.chunkOffset = 0;
  }

  process(inputs) {
    const input = inputs[0] && inputs[0][0];
    if (!input || input.length === 0) return true;

    for (let i = 0; i < input.length; i++) {
      this.accumulator += input[i];
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
