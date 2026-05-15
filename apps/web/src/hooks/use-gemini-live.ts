'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import { apiBase } from '@/lib/api';
import { getSupabaseBrowserClient } from '@/lib/supabase/client';

/**
 * `useGeminiLive` — browser WebSocket client for the FastAPI voice bridge
 * (`/ws/voice/{sessionId}`).
 *
 * This hook replaces the browser `SpeechRecognition` pathway. It opens a
 * single WS to the backend, which proxies frames to/from Gemini Live. The
 * mic worklet (see `apps/web/src/audio/capture-worklet.ts`) hands us Int16
 * PCM chunks at 16 kHz; we forward each via `pushAudio` as a base64-encoded
 * `{"type":"audio"}` frame. Inbound `{"type":"audio"}` frames are decoded
 * and pushed to the playback worklet via `audioChunk$` (Float32 PCM 24k).
 *
 * Lifecycle (state machine — mirrors docs/interruption-architecture.md):
 *
 *   idle → connecting → listening ⇄ speaking → (turn_complete) listening
 *                                  ↘ (interrupted) listening
 *                       → closed | error
 *
 * Auto-reconnect is intentionally NOT implemented for v1 — the overlay is
 * short-lived and the user can re-open on a drop.
 */

export type GeminiLiveState =
  | 'idle'
  | 'connecting'
  | 'listening'
  | 'speaking'
  | 'closed'
  | 'error';

export interface UseGeminiLiveArgs {
  /** Backend session UUID (from `/v1/sessions`). When null, the hook stays idle. */
  sessionId: string | null;
  /** Optional topic slug forwarded to the server for prompt context. */
  topic?: string | null;
  /** Called with each `{"type":"transcript"}` fragment from the server. */
  onTranscript?: (text: string) => void;
  /**
   * Called when the server signals `{"type":"interrupted"}` — the consumer
   * MUST flush its TTS playback queue immediately (drop buffered audio).
   */
  onInterrupted?: () => void;
  /** Called on `{"type":"turn_complete"}` — model has finished speaking. */
  onTurnComplete?: () => void;
  /** Called when the bridge surfaces an error frame. */
  onError?: (message: string) => void;
}

export interface UseGeminiLiveResult {
  state: GeminiLiveState;
  /** Open the WS and transition idle → connecting → listening. */
  start: () => Promise<void>;
  /** Close the WS cleanly. State becomes 'closed'. */
  stop: () => void;
  /**
   * Client-initiated barge-in: send `{"type":"interrupt"}` so the model
   * yields without VAD detecting student speech.
   */
  interrupt: () => void;
  /** Forward a single 16 kHz Int16 PCM chunk from the capture worklet. */
  pushAudio: (pcm16: Int16Array) => void;
  /**
   * Subscribe to inbound audio frames (Float32 PCM 24 kHz). Returns an
   * unsubscribe handle. Used by the consumer to feed the playback worklet.
   */
  audioChunk$: (cb: (samples: Float32Array) => void) => () => void;
}

interface ServerFrame {
  type: string;
  audio?: string;
  text?: string;
  message?: string;
}

/**
 * Decode a base64 PCM16 string from the server into Float32 samples in
 * [-1, 1]. The playback worklet's `push` handler accepts either Int16 or
 * Float32; we normalise to Float32 here so consumers don't have to.
 */
function decodeBase64Pcm16(b64: string): Float32Array {
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  const view = new DataView(bytes.buffer);
  const sampleCount = bytes.length >> 1;
  const out = new Float32Array(sampleCount);
  for (let i = 0; i < sampleCount; i++) {
    // Little-endian Int16 → normalised float.
    out[i] = view.getInt16(i * 2, true) / 32768;
  }
  return out;
}

/**
 * Encode an Int16 mic chunk to base64 for the JSON envelope. The capture
 * worklet posts transferable Int16Array buffers ~100 ms long (1600
 * samples), so the underlying byte length is ~3.2 KB — well within the
 * range where `String.fromCharCode(...spread)` + `btoa` is the simplest
 * working approach (no copy required for the read; `btoa` makes its own).
 */
function encodePcm16ToBase64(pcm16: Int16Array): string {
  const bytes = new Uint8Array(pcm16.buffer, pcm16.byteOffset, pcm16.byteLength);
  // Chunked to avoid blowing the JS call-stack on very large frames; for
  // ~3 KB chunks this loop runs once.
  const CHUNK = 0x8000;
  let binary = '';
  for (let i = 0; i < bytes.length; i += CHUNK) {
    binary += String.fromCharCode(...bytes.subarray(i, i + CHUNK));
  }
  return btoa(binary);
}

/** Compose the WS URL from `apiBase` (http/https → ws/wss). */
function buildWsUrl(sessionId: string, topic: string | null, token: string | null): string {
  const base = apiBase.replace(/^http/, 'ws');
  const params = new URLSearchParams();
  if (topic) params.set('topic', topic);
  if (token) params.set('token', token);
  const qs = params.toString();
  return `${base}/ws/voice/${sessionId}${qs ? `?${qs}` : ''}`;
}

export function useGeminiLive({
  sessionId,
  topic,
  onTranscript,
  onInterrupted,
  onTurnComplete,
  onError,
}: UseGeminiLiveArgs): UseGeminiLiveResult {
  const [state, setState] = useState<GeminiLiveState>('idle');

  // Mutable refs — callbacks must remain stable across renders so the
  // VoiceMode component doesn't churn the start/stop effect.
  const wsRef = useRef<WebSocket | null>(null);
  const stateRef = useRef<GeminiLiveState>('idle');
  const onTranscriptRef = useRef(onTranscript);
  const onInterruptedRef = useRef(onInterrupted);
  const onTurnCompleteRef = useRef(onTurnComplete);
  const onErrorRef = useRef(onError);
  /** Subscribers for inbound PCM (decoded Float32, 24 kHz). */
  const audioListenersRef = useRef<Set<(samples: Float32Array) => void>>(new Set());

  useEffect(() => {
    onTranscriptRef.current = onTranscript;
  }, [onTranscript]);
  useEffect(() => {
    onInterruptedRef.current = onInterrupted;
  }, [onInterrupted]);
  useEffect(() => {
    onTurnCompleteRef.current = onTurnComplete;
  }, [onTurnComplete]);
  useEffect(() => {
    onErrorRef.current = onError;
  }, [onError]);

  const setStateBoth = useCallback((s: GeminiLiveState) => {
    stateRef.current = s;
    setState(s);
  }, []);

  /**
   * Resolve the Supabase access token. In DEMO_MODE we return null and
   * let the backend's DEV_MODE shortcut accept the connection without auth.
   */
  const resolveToken = useCallback(async (): Promise<string | null> => {
    if (process.env.NEXT_PUBLIC_DEMO_MODE === 'true') return null;
    if (typeof window === 'undefined') return null;
    try {
      const supabase = getSupabaseBrowserClient();
      const { data } = await supabase.auth.getSession();
      return data.session?.access_token ?? null;
    } catch {
      // Env vars missing / auth unavailable — let the backend reject if it must.
      return null;
    }
  }, []);

  const start = useCallback(async () => {
    if (!sessionId) return;
    if (wsRef.current && stateRef.current !== 'closed' && stateRef.current !== 'error') {
      // Already open / opening — no-op.
      return;
    }
    setStateBoth('connecting');

    const token = await resolveToken();
    const url = buildWsUrl(sessionId, topic ?? null, token);

    let ws: WebSocket;
    try {
      ws = new WebSocket(url);
    } catch (e) {
      setStateBoth('error');
      onErrorRef.current?.((e as Error).message);
      return;
    }
    wsRef.current = ws;

    ws.onopen = () => {
      // The bridge sends `{type:"ready"}` first; until then we sit in
      // 'connecting'. We optimistically flip to 'listening' here so the
      // mic capture worklet can start streaming immediately — the bridge
      // queues frames during the handshake.
      setStateBoth('listening');
    };

    ws.onmessage = (event) => {
      let frame: ServerFrame;
      try {
        frame = JSON.parse(event.data as string) as ServerFrame;
      } catch {
        return;
      }
      switch (frame.type) {
        case 'ready':
          // Already 'listening' from onopen — nothing to do.
          break;
        case 'audio': {
          if (!frame.audio) break;
          // Model is producing audio → state = 'speaking'.
          if (stateRef.current !== 'speaking') setStateBoth('speaking');
          const samples = decodeBase64Pcm16(frame.audio);
          audioListenersRef.current.forEach((cb) => cb(samples));
          break;
        }
        case 'transcript':
          if (frame.text) onTranscriptRef.current?.(frame.text);
          break;
        case 'interrupted':
          // Critical: consumer must flush playback NOW. We also flip the
          // visible state back to 'listening' so the "Aria speaking"
          // indicator clears even if the next frame is `generation_complete`.
          setStateBoth('listening');
          onInterruptedRef.current?.();
          break;
        case 'generation_complete':
          // Model has stopped producing — but queued audio may still be
          // playing. We leave state as 'speaking' until `turn_complete`
          // so the UI hint stays accurate.
          break;
        case 'turn_complete':
          setStateBoth('listening');
          onTurnCompleteRef.current?.();
          break;
        case 'error':
          setStateBoth('error');
          onErrorRef.current?.(frame.message ?? 'unknown error');
          break;
        case 'done':
          // Bridge has cleanly torn down. The matching onclose will flip
          // state to 'closed' shortly.
          break;
        default:
          // Unknown frame — ignore.
          break;
      }
    };

    ws.onerror = () => {
      // The Browser WS error event is opaque — surface a generic message.
      // The matching onclose will follow and is where we settle terminal state.
      onErrorRef.current?.('websocket error');
    };

    ws.onclose = () => {
      // Only land in 'closed' if we weren't already in 'error' so the
      // consumer can distinguish "user closed" from "auth failed".
      if (stateRef.current !== 'error') setStateBoth('closed');
      wsRef.current = null;
    };
  }, [sessionId, topic, resolveToken, setStateBoth]);

  const stop = useCallback(() => {
    const ws = wsRef.current;
    if (!ws) {
      setStateBoth('closed');
      return;
    }
    try {
      // 1000 = normal closure. The bridge tears down the Gemini session
      // when the WS closes, so no further cleanup is needed client-side.
      ws.close(1000, 'client closed');
    } catch {
      // ignore — onclose will fire regardless
    }
  }, [setStateBoth]);

  const interrupt = useCallback(() => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    try {
      ws.send(JSON.stringify({ type: 'interrupt' }));
    } catch {
      // best-effort — the WS will close shortly if the send failed
    }
  }, []);

  const pushAudio = useCallback((pcm16: Int16Array) => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    try {
      const audio = encodePcm16ToBase64(pcm16);
      ws.send(JSON.stringify({ type: 'audio', audio }));
    } catch {
      // ignore — most likely the socket closed between the readyState
      // check and send. The next push will set state appropriately.
    }
  }, []);

  const audioChunk$ = useCallback((cb: (samples: Float32Array) => void) => {
    audioListenersRef.current.add(cb);
    return () => {
      audioListenersRef.current.delete(cb);
    };
  }, []);

  // Cleanup on unmount — make sure we don't leak a dangling socket.
  // We capture refs to local consts so the eslint react-hooks/exhaustive-deps
  // "ref may change before cleanup runs" warning doesn't fire; the Set
  // identity is stable across the component's lifetime anyway.
  useEffect(() => {
    const listeners = audioListenersRef.current;
    return () => {
      const ws = wsRef.current;
      if (ws && ws.readyState === WebSocket.OPEN) {
        try {
          ws.close(1000, 'unmount');
        } catch {
          // ignore
        }
      }
      wsRef.current = null;
      listeners.clear();
    };
  }, []);

  return { state, start, stop, interrupt, pushAudio, audioChunk$ };
}
