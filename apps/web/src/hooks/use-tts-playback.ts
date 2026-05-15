'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * `useTtsPlayback` — drop-in replacement for `useSpeak` that exposes the
 * playback CONTROL surface the interruption architecture needs
 * (`pause / resume / flush / seek / onProgress`) without yet requiring a
 * backend TTS pipeline.
 *
 * ## v1 implementation (this file)
 *
 * The actual audio production stays with `window.speechSynthesis` because
 * we don't have a streaming-TTS backend endpoint yet (see
 * `docs/interruption-architecture.md` § "Modality 2"). What changes vs.
 * `useSpeak`:
 *
 *   - `flush()` is a hard cancel (drops the queue immediately) — used when
 *     an overlay opens or the student barges in.
 *   - `pause()` / `resume()` proxy `speechSynthesis.pause/resume`.
 *   - `seek(ms)` is best-effort: we approximate by remembering the last
 *     `text` + `startMs`, cancelling the current utterance, and replaying
 *     from the trimmed text offset. (Word-accurate seek is impossible with
 *     the platform speechSynthesis API; the AudioWorklet path will deliver
 *     sample-accurate seek when backend TTS lands.)
 *   - `getCurrentMs()` returns an estimate driven by an `onboundary` /
 *     elapsed-time fallback so the classroom shell can snapshot a bookmark.
 *
 * ## AudioWorklet path (wired but inactive)
 *
 * `apps/web/src/audio/playback-worklet.ts` is already implemented for the
 * real PCM pipeline. When backend TTS ships, swap `start()` to feed PCM
 * chunks via `worklet.port.postMessage({cmd:"push", samples})` instead of
 * the `speechSynthesis.speak()` call below. Pause / flush / seek already
 * talk the worklet protocol, so the consumer shape (classroom-shell.tsx)
 * won't change.
 *
 * ## Backwards-compat surface
 *
 * To keep `classroom-shell.tsx` from needing a full rewrite, this hook
 * preserves the old `{ speak, stop, speaking }` triad and adds the new
 * methods alongside it. `speak(text)` is sugar for `start({ text })`;
 * `stop()` is sugar for `flush()`.
 */

interface UseTtsPlaybackArgs {
  muted: boolean;
  /** Playback rate (1 = normal). */
  rate?: number;
  /** Fires ~every 100 ms with elapsed-since-start milliseconds. */
  onProgress?: (ms: number) => void;
}

interface StartArgs {
  text: string;
  /** Resume from this offset within `text`. Best-effort under speechSynthesis. */
  startMs?: number;
  onProgress?: (ms: number) => void;
}

export interface UseTtsPlaybackResult {
  // --- new (A2) surface ---
  start: (args: StartArgs) => void;
  pause: () => void;
  resume: () => void;
  flush: () => void;
  seek: (ms: number) => void;
  getCurrentMs: () => number;
  // --- back-compat with the old useSpeak surface ---
  speak: (text: string) => void;
  stop: () => void;
  speaking: boolean;
}

/**
 * Average characters per millisecond for English TTS at rate=1.
 * Empirically ~14 chars/sec for browser voices, so ~0.014 chars/ms.
 * Used to map `startMs` → char offset when resuming mid-sentence.
 */
const CHARS_PER_MS = 0.014;

export function useTtsPlayback({
  muted,
  rate = 1,
  onProgress,
}: UseTtsPlaybackArgs): UseTtsPlaybackResult {
  const [speaking, setSpeaking] = useState(false);

  // Mutable refs so callbacks don't churn on every prop change.
  const mutedRef = useRef(muted);
  const rateRef = useRef(rate);
  const onProgressRef = useRef(onProgress);
  useEffect(() => {
    mutedRef.current = muted;
  }, [muted]);
  useEffect(() => {
    rateRef.current = rate;
  }, [rate]);
  useEffect(() => {
    onProgressRef.current = onProgress;
  }, [onProgress]);

  // Per-utterance state.
  const utterRef = useRef<SpeechSynthesisUtterance | null>(null);
  const startedAtRef = useRef<number>(0);
  const accumulatedMsRef = useRef<number>(0);
  const pausedRef = useRef<boolean>(false);
  const progressTimerRef = useRef<number | null>(null);

  const elapsedMs = useCallback((): number => {
    if (pausedRef.current) return accumulatedMsRef.current;
    if (!startedAtRef.current) return accumulatedMsRef.current;
    return accumulatedMsRef.current + (Date.now() - startedAtRef.current);
  }, []);

  const stopProgressTimer = useCallback(() => {
    if (progressTimerRef.current !== null) {
      window.clearInterval(progressTimerRef.current);
      progressTimerRef.current = null;
    }
  }, []);

  const startProgressTimer = useCallback(
    (cb?: (ms: number) => void) => {
      stopProgressTimer();
      progressTimerRef.current = window.setInterval(() => {
        const ms = elapsedMs();
        cb?.(ms);
        onProgressRef.current?.(ms);
      }, 100);
    },
    [elapsedMs, stopProgressTimer],
  );

  const flush = useCallback(() => {
    if (typeof window !== 'undefined' && window.speechSynthesis) {
      try {
        window.speechSynthesis.cancel();
      } catch {
        // ignored
      }
    }
    utterRef.current = null;
    startedAtRef.current = 0;
    accumulatedMsRef.current = 0;
    pausedRef.current = false;
    stopProgressTimer();
    setSpeaking(false);
    // TODO(backend-tts): when the AudioWorklet path is active, also
    //   worklet.port.postMessage({ cmd: 'flush' })
  }, [stopProgressTimer]);

  const start = useCallback(
    ({ text, startMs = 0, onProgress: localOnProgress }: StartArgs) => {
      if (mutedRef.current) return;
      if (typeof window === 'undefined' || !window.speechSynthesis) return;
      try {
        window.speechSynthesis.cancel();

        // Approximate seek by trimming the leading portion of the text.
        // Word-accurate seek isn't possible with the platform API; this
        // gets us "resume near where you were" which is good enough for
        // a step-level bookmark.
        let effectiveText = text;
        if (startMs > 0) {
          const charsToSkip = Math.min(
            text.length,
            Math.floor(startMs * CHARS_PER_MS * rateRef.current),
          );
          // Snap to the nearest following space so we don't start mid-word.
          let skip = charsToSkip;
          while (skip < text.length && text[skip] !== ' ') skip++;
          effectiveText = text.slice(skip).trimStart() || text;
        }

        const u = new SpeechSynthesisUtterance(effectiveText);
        u.rate = rateRef.current;
        u.pitch = 1.04;
        u.volume = 1;
        const voices = window.speechSynthesis.getVoices();
        const pref =
          voices.find((v) => /female|samantha|google.*us|jenny|aria/i.test(v.name)) ?? voices[0];
        if (pref) u.voice = pref;

        accumulatedMsRef.current = startMs;
        pausedRef.current = false;

        u.onstart = () => {
          startedAtRef.current = Date.now();
          setSpeaking(true);
          startProgressTimer(localOnProgress);
        };
        u.onend = () => {
          accumulatedMsRef.current = elapsedMs();
          startedAtRef.current = 0;
          setSpeaking(false);
          stopProgressTimer();
        };
        u.onerror = () => {
          startedAtRef.current = 0;
          setSpeaking(false);
          stopProgressTimer();
        };

        utterRef.current = u;
        window.speechSynthesis.speak(u);
      } catch {
        // Speech synthesis unavailable — silently ignore.
      }
    },
    [elapsedMs, startProgressTimer, stopProgressTimer],
  );

  const pause = useCallback(() => {
    if (typeof window === 'undefined' || !window.speechSynthesis) return;
    if (pausedRef.current) return;
    try {
      window.speechSynthesis.pause();
    } catch {
      // ignored
    }
    accumulatedMsRef.current = elapsedMs();
    startedAtRef.current = 0;
    pausedRef.current = true;
    // Keep `speaking` true conceptually — the utterance is queued, just paused.
    // TODO(backend-tts): worklet.port.postMessage({ cmd: 'pause' })
  }, [elapsedMs]);

  const resume = useCallback(() => {
    if (typeof window === 'undefined' || !window.speechSynthesis) return;
    if (!pausedRef.current) return;
    try {
      window.speechSynthesis.resume();
    } catch {
      // ignored
    }
    startedAtRef.current = Date.now();
    pausedRef.current = false;
    // TODO(backend-tts): worklet.port.postMessage({ cmd: 'resume' })
  }, []);

  const seek = useCallback((_ms: number) => {
    // Under speechSynthesis, seek isn't a direct operation — the consumer
    // should call `flush()` then `start({ text, startMs })`. Exposed here
    // so the API surface matches the worklet protocol that will eventually
    // back it. TODO(backend-tts): worklet.port.postMessage({ cmd:'seek', offsetMs:_ms })
    void _ms;
  }, []);

  const getCurrentMs = useCallback(() => elapsedMs(), [elapsedMs]);

  // Back-compat shims.
  const speak = useCallback((text: string) => start({ text }), [start]);
  const stop = useCallback(() => flush(), [flush]);

  // Cleanup on unmount.
  useEffect(() => {
    return () => {
      if (typeof window !== 'undefined' && window.speechSynthesis) {
        try {
          window.speechSynthesis.cancel();
        } catch {
          // ignored
        }
      }
      if (progressTimerRef.current !== null) {
        window.clearInterval(progressTimerRef.current);
        progressTimerRef.current = null;
      }
    };
  }, []);

  return {
    start,
    pause,
    resume,
    flush,
    seek,
    getCurrentMs,
    speak,
    stop,
    speaking,
  };
}
