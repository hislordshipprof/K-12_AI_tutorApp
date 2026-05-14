'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

/* eslint-disable @typescript-eslint/no-explicit-any */

interface UseListenResult {
  listening: boolean;
  transcript: string;
  start: () => void;
  stop: () => void;
  setTranscript: (s: string) => void;
}

const MOCK_QUESTIONS = [
  'What does amplitude mean again?',
  'How is wavelength different from period?',
  'Can you show me v equals f times lambda?',
  'What unit is frequency measured in?',
  'Wait, are crests always at the top?',
];

/**
 * Speech recognition with a mock fallback.
 *
 * Tries `webkitSpeechRecognition`/`SpeechRecognition` first; if neither is
 * available (Firefox, SSR, etc.) it types out a random mock question
 * letter-by-letter so the rest of the voice UX still demonstrates well.
 */
export function useListen(): UseListenResult {
  const [listening, setListening] = useState(false);
  const [transcript, setTranscript] = useState('');
  const recRef = useRef<any>(null);
  const mockRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const start = useCallback(() => {
    setTranscript('');
    setListening(true);

    if (typeof window === 'undefined') return;

    const win = window as unknown as {
      SpeechRecognition?: any;
      webkitSpeechRecognition?: any;
    };
    const SR = win.SpeechRecognition ?? win.webkitSpeechRecognition;
    if (SR) {
      try {
        const rec = new SR();
        rec.continuous = false;
        rec.interimResults = true;
        rec.lang = 'en-US';
        rec.onresult = (e: any) => {
          const t = Array.from(e.results as ArrayLike<any>)
            .map((r: any) => r[0].transcript)
            .join('');
          setTranscript(t);
        };
        rec.onend = () => setListening(false);
        rec.onerror = () => setListening(false);
        rec.start();
        recRef.current = rec;
        return;
      } catch {
        // fall through to mock
      }
    }

    // Mock — type out a random question letter by letter.
    const mock = MOCK_QUESTIONS[Math.floor(Math.random() * MOCK_QUESTIONS.length)] ?? '';
    let i = 0;
    mockRef.current = setInterval(() => {
      i += 1 + Math.floor(Math.random() * 2);
      const piece = mock.slice(0, Math.min(i, mock.length));
      setTranscript(piece);
      if (i >= mock.length && mockRef.current) {
        clearInterval(mockRef.current);
        mockRef.current = null;
      }
    }, 70);
  }, []);

  const stop = useCallback(() => {
    if (recRef.current) {
      try {
        recRef.current.stop();
      } catch {
        // ignore
      }
      recRef.current = null;
    }
    if (mockRef.current) {
      clearInterval(mockRef.current);
      mockRef.current = null;
    }
    setListening(false);
  }, []);

  // Cleanup on unmount.
  useEffect(() => {
    return () => {
      if (recRef.current) {
        try {
          recRef.current.stop();
        } catch {
          // ignore
        }
        recRef.current = null;
      }
      if (mockRef.current) {
        clearInterval(mockRef.current);
        mockRef.current = null;
      }
    };
  }, []);

  return { listening, transcript, start, stop, setTranscript };
}
