'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import { apiBase } from '@/lib/api';

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
  /** Fetch + cache TTS for `text` so a later `start()` plays instantly. */
  prefetch: (text: string) => void;
  // --- back-compat with the old useSpeak surface ---
  speak: (text: string) => void;
  stop: () => void;
  speaking: boolean;
  /**
   * Playback progress 0→1 for the current utterance, updated continuously
   * while audio plays. Drives the word-timed "writing as she speaks"
   * reveal in the classroom (Phase A). Resets to 0 on flush / new start.
   */
  progress: number;
}

/**
 * Average characters per millisecond for English TTS at rate=1.
 * Empirically ~14 chars/sec for browser voices, so ~0.014 chars/ms.
 * Used to map `startMs` → char offset when resuming mid-sentence.
 */
const CHARS_PER_MS = 0.014;

/**
 * Pick the most natural-sounding voice the browser ships with. The order
 * matches subjective quality (most natural → least): Microsoft Online
 * neural voices, Google "Natural" / "Wavenet" voices, then any "Aria" /
 * "Jenny" / "Samantha" preset, then anything female-flagged, finally the
 * first English voice we can find. Falls back to the platform default.
 */
function pickNaturalVoice(): SpeechSynthesisVoice | null {
  if (typeof window === 'undefined' || !window.speechSynthesis) return null;
  const voices = window.speechSynthesis.getVoices();
  if (voices.length === 0) return null;

  const matchers: Array<(v: SpeechSynthesisVoice) => boolean> = [
    // Top-tier: Microsoft Edge neural voices (Aria, Sonia, Jenny, Libby).
    (v) => /Microsoft.+(Aria|Sonia|Jenny|Libby|Emma|Ava).+Online/i.test(v.name),
    (v) => /Microsoft.+Online.+Natural/i.test(v.name),
    // Google Wavenet / Neural voices (Chrome on some platforms).
    (v) => /Google.+(Wavenet|Neural|Studio)/i.test(v.name),
    // Any voice that self-identifies as "Natural" / "Neural".
    (v) => /Natural|Neural/i.test(v.name),
    // Apple's premium voices.
    (v) => /Samantha|Ava|Allison|Karen/i.test(v.name) && /en/i.test(v.lang),
    // Aria-themed presets.
    (v) => /aria/i.test(v.name) && /en/i.test(v.lang),
    // Any English female voice.
    (v) => /female/i.test(v.name) && /en/i.test(v.lang),
    // Windows SAPI: Zira is the cleanest female of the legacy trio
    // (David/Mark/Zira). Beats falling through to David which sounds
    // particularly synthetic. NOTE: this is still robotic — installing
    // a neural voice package (Edge → Settings → Languages → English →
    // Speech → "Microsoft Aria — Online") gives a dramatically better
    // result and the matchers above will pick it up automatically.
    (v) => /\bZira\b/i.test(v.name),
    // Any English voice at all.
    (v) => /en[-_]?US|en[-_]?GB|en$/i.test(v.lang),
  ];

  for (const test of matchers) {
    const found = voices.find(test);
    if (found) return found;
  }
  return voices[0] ?? null;
}

export function useTtsPlayback({
  muted,
  rate = 1,
  onProgress,
}: UseTtsPlaybackArgs): UseTtsPlaybackResult {
  const [speaking, setSpeaking] = useState(false);
  // 0→1 playback progress for the current utterance. Components subscribe
  // to this to drive the word-timed reveal animation.
  const [progress, setProgress] = useState(0);

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
  // HTMLAudioElement-backed playback (Gemini Live WAV).
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const audioUrlRef = useRef<string | null>(null);
  // Tracks the in-flight TTS fetch so a flush() can abort it before audio loads.
  const ttsAbortRef = useRef<AbortController | null>(null);
  // Pre-fetch cache: text → blob URL. Hides the ~3-5s Gemini Live latency
  // when the classroom shell warms up the next lesson step while the
  // current one plays. Keeps last ~4 entries; oldest gets revoked.
  const prefetchCacheRef = useRef<Map<string, string>>(new Map());
  const PREFETCH_CACHE_MAX = 4;
  const startedAtRef = useRef<number>(0);
  const accumulatedMsRef = useRef<number>(0);
  const pausedRef = useRef<boolean>(false);
  const progressTimerRef = useRef<number | null>(null);

  /** Internal — POST /v1/tts and return a blob URL. Used by both
   *  `start()` (when cache misses) and `prefetch()` (warm-up). */
  const fetchTtsBlobUrl = useCallback(
    async (text: string, signal: AbortSignal): Promise<string> => {
      const res = await fetch(`${apiBase}/v1/tts`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'audio/wav',
          ...(process.env.NEXT_PUBLIC_DEMO_MODE === 'true'
            ? { 'X-Dev-User-Id': '00000000-0000-0000-0000-000000000001' }
            : {}),
        },
        body: JSON.stringify({ text }),
        signal,
      });
      if (!res.ok) throw new Error(`tts ${res.status}`);
      const blob = await res.blob();
      return URL.createObjectURL(blob);
    },
    [],
  );

  /** Eject the oldest cache entry when we're at capacity. */
  const trimPrefetchCache = useCallback(() => {
    while (prefetchCacheRef.current.size > PREFETCH_CACHE_MAX) {
      const oldestKey = prefetchCacheRef.current.keys().next().value;
      if (oldestKey === undefined) break;
      const url = prefetchCacheRef.current.get(oldestKey);
      if (url) {
        try {
          URL.revokeObjectURL(url);
        } catch {
          // ignored
        }
      }
      prefetchCacheRef.current.delete(oldestKey);
    }
  }, []);

  const releaseAudio = useCallback(() => {
    const a = audioRef.current;
    if (a) {
      try {
        a.pause();
        a.removeAttribute('src');
        a.load();
      } catch {
        // ignored
      }
    }
    audioRef.current = null;
    // Only revoke the URL if it isn't sitting in the prefetch cache — a
    // pre-warmed clip should survive its first play so a back-button or
    // step-revisit still gets the cached version.
    if (audioUrlRef.current) {
      const cached = Array.from(prefetchCacheRef.current.values()).includes(
        audioUrlRef.current,
      );
      if (!cached) {
        try {
          URL.revokeObjectURL(audioUrlRef.current);
        } catch {
          // ignored
        }
      }
      audioUrlRef.current = null;
    }
  }, []);

  const prefetch = useCallback(
    (text: string) => {
      if (mutedRef.current) return;
      const key = text.trim();
      if (!key) return;
      if (prefetchCacheRef.current.has(key)) return;
      // Fire and forget. Aborts on unmount via the unmount cleanup.
      const controller = new AbortController();
      void fetchTtsBlobUrl(key, controller.signal)
        .then((url) => {
          prefetchCacheRef.current.set(key, url);
          trimPrefetchCache();
        })
        .catch(() => {
          // Prefetch errors are silent — the start() path will retry
          // and fall back to speechSynthesis if the second attempt fails.
        });
    },
    [fetchTtsBlobUrl, trimPrefetchCache],
  );

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
    // Abort any in-flight /v1/tts fetch so we don't start playing an audio
    // clip after the user has barged in.
    if (ttsAbortRef.current) {
      try {
        ttsAbortRef.current.abort();
      } catch {
        // ignored
      }
      ttsAbortRef.current = null;
    }
    releaseAudio();
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
    setProgress(0);
  }, [releaseAudio, stopProgressTimer]);

  /**
   * Fallback path — use the browser's speechSynthesis API. Used when the
   * Gemini Live fetch fails, returns a non-2xx, or is explicitly disabled.
   */
  const startWithWebSpeech = useCallback(
    (
      text: string,
      startMs: number,
      localOnProgress?: (ms: number) => void,
    ) => {
      if (typeof window === 'undefined' || !window.speechSynthesis) return;
      try {
        window.speechSynthesis.cancel();

        // Approximate seek by trimming the leading portion of the text.
        let effectiveText = text;
        if (startMs > 0) {
          const charsToSkip = Math.min(
            text.length,
            Math.floor(startMs * CHARS_PER_MS * rateRef.current),
          );
          let skip = charsToSkip;
          while (skip < text.length && text[skip] !== ' ') skip++;
          effectiveText = text.slice(skip).trimStart() || text;
        }

        const u = new SpeechSynthesisUtterance(effectiveText);
        u.rate = Math.max(0.85, rateRef.current * 0.92);
        u.pitch = 1.0;
        u.volume = 1;
        const pref = pickNaturalVoice();
        if (pref) u.voice = pref;

        accumulatedMsRef.current = startMs;
        pausedRef.current = false;

        u.onstart = () => {
          startedAtRef.current = Date.now();
          setSpeaking(true);
          startProgressTimer(localOnProgress);
        };
        // speechSynthesis has no media clock — approximate progress from
        // the boundary event's charIndex over the utterance length.
        u.onboundary = (e: SpeechSynthesisEvent) => {
          if (effectiveText.length > 0) {
            setProgress(Math.min(1, e.charIndex / effectiveText.length));
          }
        };
        u.onend = () => {
          accumulatedMsRef.current = elapsedMs();
          startedAtRef.current = 0;
          setSpeaking(false);
          setProgress(1);
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

  /**
   * Primary path — fetch a natural-voice WAV from /v1/tts and play it via
   * an HTMLAudioElement. Falls back to speechSynthesis on any failure so
   * a TTS outage doesn't silence the lesson.
   */
  const start = useCallback(
    ({ text, startMs = 0, onProgress: localOnProgress }: StartArgs) => {
      if (mutedRef.current) return;
      if (!text.trim()) return;

      // Reset reveal progress for the new utterance.
      setProgress(0);

      // Clean slate before kicking a new utterance.
      if (ttsAbortRef.current) {
        try {
          ttsAbortRef.current.abort();
        } catch {
          // ignored
        }
      }
      releaseAudio();
      if (typeof window !== 'undefined' && window.speechSynthesis) {
        try {
          window.speechSynthesis.cancel();
        } catch {
          // ignored
        }
      }
      stopProgressTimer();

      accumulatedMsRef.current = startMs;
      pausedRef.current = false;

      const controller = new AbortController();
      ttsAbortRef.current = controller;

      // Kick off the fetch — show the "speaking" state optimistically so
      // the UI doesn't flash idle during the ~500ms-2s synth latency.
      setSpeaking(true);

      (async () => {
        try {
          // Cache hit — a previous prefetch() warmed this clip. Skip
          // the network round-trip entirely; playback starts in ms.
          const cacheKey = text.trim();
          let url: string;
          const cached = prefetchCacheRef.current.get(cacheKey);
          if (cached) {
            url = cached;
            // Remove from cache so a subsequent start() with the same
            // text re-fetches (the blob URL gets revoked on releaseAudio
            // unless it stays cached — but we want it played only once).
            prefetchCacheRef.current.delete(cacheKey);
          } else {
            url = await fetchTtsBlobUrl(text, controller.signal);
            if (controller.signal.aborted) return;
          }
          audioUrlRef.current = url;
          const audio = new Audio(url);
          audio.preload = 'auto';
          audio.playbackRate = Math.max(0.85, rateRef.current * 0.95);
          audioRef.current = audio;

          audio.onloadedmetadata = () => {
            if (startMs > 0 && Number.isFinite(audio.duration)) {
              audio.currentTime = Math.min(audio.duration - 0.05, startMs / 1000);
            }
          };
          audio.onplay = () => {
            startedAtRef.current = Date.now();
            setSpeaking(true);
            startProgressTimer(localOnProgress);
          };
          // Sample-accurate progress straight off the media clock —
          // drives the word-timed reveal in the classroom.
          audio.ontimeupdate = () => {
            if (Number.isFinite(audio.duration) && audio.duration > 0) {
              setProgress(Math.min(1, audio.currentTime / audio.duration));
            }
          };
          audio.onpause = () => {
            accumulatedMsRef.current = elapsedMs();
            startedAtRef.current = 0;
            // Keep speaking=true while paused so the UI shows the bar; flush()
            // sets it to false explicitly.
          };
          audio.onended = () => {
            accumulatedMsRef.current = elapsedMs();
            startedAtRef.current = 0;
            setSpeaking(false);
            setProgress(1);
            stopProgressTimer();
            releaseAudio();
          };
          audio.onerror = () => {
            startedAtRef.current = 0;
            setSpeaking(false);
            stopProgressTimer();
            releaseAudio();
            // Last-ditch — try the platform voice so the student hears
            // *something* instead of silence.
            startWithWebSpeech(text, startMs, localOnProgress);
          };

          await audio.play().catch(() => {
            // Autoplay blocked — fall back to platform voice. Browsers
            // typically allow audio after the user has interacted with
            // the page (which a classroom click implies).
            releaseAudio();
            startWithWebSpeech(text, startMs, localOnProgress);
          });
        } catch (err) {
          if (controller.signal.aborted) return;
          // Network blip / 502 / no API key — fall back to platform voice.
          void err;
          startWithWebSpeech(text, startMs, localOnProgress);
        } finally {
          if (ttsAbortRef.current === controller) {
            ttsAbortRef.current = null;
          }
        }
      })();
    },
    [
      elapsedMs,
      releaseAudio,
      startProgressTimer,
      startWithWebSpeech,
      stopProgressTimer,
    ],
  );

  const pause = useCallback(() => {
    if (pausedRef.current) return;
    // Prefer the audio-element path; if it's not active, fall back to
    // speechSynthesis so legacy plays still pause cleanly.
    const audio = audioRef.current;
    if (audio && !audio.paused) {
      try {
        audio.pause();
      } catch {
        // ignored
      }
    } else if (typeof window !== 'undefined' && window.speechSynthesis) {
      try {
        window.speechSynthesis.pause();
      } catch {
        // ignored
      }
    }
    accumulatedMsRef.current = elapsedMs();
    startedAtRef.current = 0;
    pausedRef.current = true;
  }, [elapsedMs]);

  const resume = useCallback(() => {
    if (!pausedRef.current) return;
    const audio = audioRef.current;
    if (audio) {
      audio.play().catch(() => {
        // Autoplay block — keep the paused state truthful.
      });
    } else if (typeof window !== 'undefined' && window.speechSynthesis) {
      try {
        window.speechSynthesis.resume();
      } catch {
        // ignored
      }
    }
    startedAtRef.current = Date.now();
    pausedRef.current = false;
  }, []);

  const seek = useCallback((ms: number) => {
    const audio = audioRef.current;
    if (audio && Number.isFinite(audio.duration)) {
      try {
        audio.currentTime = Math.max(0, Math.min(audio.duration - 0.05, ms / 1000));
        accumulatedMsRef.current = ms;
      } catch {
        // ignored
      }
      return;
    }
    // speechSynthesis has no native seek — consumer should flush + restart.
    void ms;
  }, []);

  const getCurrentMs = useCallback(() => {
    // When the audio-element path is active prefer its own clock — it's
    // sample-accurate and survives pause/resume cycles correctly.
    const audio = audioRef.current;
    if (audio && Number.isFinite(audio.currentTime)) {
      return Math.round(audio.currentTime * 1000);
    }
    return elapsedMs();
  }, [elapsedMs]);

  // Back-compat shims.
  const speak = useCallback((text: string) => start({ text }), [start]);
  const stop = useCallback(() => flush(), [flush]);

  // Cleanup on unmount.
  useEffect(() => {
    return () => {
      if (ttsAbortRef.current) {
        try {
          ttsAbortRef.current.abort();
        } catch {
          // ignored
        }
        ttsAbortRef.current = null;
      }
      releaseAudio();
      // Revoke every cached prefetch URL — otherwise we leak blobs.
      for (const url of prefetchCacheRef.current.values()) {
        try {
          URL.revokeObjectURL(url);
        } catch {
          // ignored
        }
      }
      prefetchCacheRef.current.clear();
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Prime the speech-synthesis voice list on mount. Chrome populates
  // `getVoices()` asynchronously the first time, so without this our
  // initial `start()` call would fall back to the default robotic voice.
  useEffect(() => {
    if (typeof window === 'undefined' || !window.speechSynthesis) return;
    // Triggers the lazy load.
    window.speechSynthesis.getVoices();
    const handler = () => {
      window.speechSynthesis.getVoices();
    };
    window.speechSynthesis.addEventListener('voiceschanged', handler);
    return () => {
      window.speechSynthesis.removeEventListener('voiceschanged', handler);
    };
  }, []);

  return {
    start,
    pause,
    resume,
    flush,
    seek,
    getCurrentMs,
    prefetch,
    speak,
    stop,
    speaking,
    progress,
  };
}
