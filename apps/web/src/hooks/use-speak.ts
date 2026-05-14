'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

interface UseSpeakArgs {
  muted: boolean;
  /** Playback rate (1 = normal). */
  rate?: number;
}

interface UseSpeakResult {
  speak: (text: string) => void;
  stop: () => void;
  speaking: boolean;
}

/**
 * Thin wrapper around `window.speechSynthesis`.
 *
 * - No-ops cleanly when SSR'd (no `window`) or when `muted` is true.
 * - Cancels any in-flight utterance before queueing a new one so quick
 *   step changes don't pile up.
 */
export function useSpeak({ muted, rate = 1 }: UseSpeakArgs): UseSpeakResult {
  const [speaking, setSpeaking] = useState(false);
  const utterRef = useRef<SpeechSynthesisUtterance | null>(null);

  const speak = useCallback(
    (text: string) => {
      if (muted) return;
      if (typeof window === 'undefined' || !window.speechSynthesis) return;
      try {
        window.speechSynthesis.cancel();
        const u = new SpeechSynthesisUtterance(typeof text === 'string' ? text : String(text));
        u.rate = rate;
        u.pitch = 1.04;
        u.volume = 1;
        const voices = window.speechSynthesis.getVoices();
        const pref =
          voices.find((v) => /female|samantha|google.*us|jenny|aria/i.test(v.name)) ?? voices[0];
        if (pref) u.voice = pref;
        u.onstart = () => setSpeaking(true);
        u.onend = () => setSpeaking(false);
        u.onerror = () => setSpeaking(false);
        utterRef.current = u;
        window.speechSynthesis.speak(u);
      } catch {
        // Speech synthesis unavailable — silently ignore.
      }
    },
    [muted, rate],
  );

  const stop = useCallback(() => {
    if (typeof window !== 'undefined' && window.speechSynthesis) {
      try {
        window.speechSynthesis.cancel();
      } catch {
        // ignored
      }
    }
    setSpeaking(false);
  }, []);

  // Stop on unmount.
  useEffect(() => {
    return () => {
      if (typeof window !== 'undefined' && window.speechSynthesis) {
        try {
          window.speechSynthesis.cancel();
        } catch {
          // ignored
        }
      }
    };
  }, []);

  return { speak, stop, speaking };
}
