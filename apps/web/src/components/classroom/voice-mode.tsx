'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import { Icon } from '@/components/aria/icon';
import { Waveform } from '@/components/classroom/waveform';
import { useGeminiLive, type GeminiLiveState } from '@/hooks/use-gemini-live';
import { cn } from '@/lib/utils';

/**
 * Fullscreen voice overlay — mic orb, live transcript, cancel/send.
 *
 * **A3 rewrite**: this used to wrap browser `SpeechRecognition` via
 * `useListen`. It now opens a real WebSocket to the FastAPI voice bridge
 * (Gemini Live) and pipes the microphone — through the existing
 * `capture-worklet` — straight into the bridge as 16 kHz Int16 PCM.
 *
 * Audio coming the other way (Aria's TTS, 24 kHz PCM mono) is fanned out
 * to listeners attached via `audioChunk$`. The parent component owns the
 * playback worklet (via `useTtsPlayback`) and decides where those samples
 * go; on `onInterrupted` the parent flushes the worklet immediately so
 * Aria stops talking the instant the model yields.
 *
 * See `docs/interruption-architecture.md` § Modality 1 for the protocol +
 * state-machine details.
 */
interface VoiceModeProps {
  active: boolean;
  /** Cancel button / overlay-scrim click — closes without submitting. */
  onCancel: () => void;
  /**
   * Called when the student opts to convert the voice turn into a text
   * Q&A handoff (existing classroom-shell behaviour: open QAOverlay with
   * the transcript as the initial question).
   */
  onSubmit: (text: string) => void;
  /** Backend session UUID; if null we render the shell without connecting. */
  sessionId: string | null;
  /** Topic slug forwarded to the bridge for system-prompt context. */
  topic?: string | null;
  /**
   * Inbound Float32 PCM (24 kHz) push handle from the parent's playback
   * worklet. The hook decodes server `{type:"audio"}` frames to Float32
   * and hands them to this callback.
   */
  onAudioChunk?: (samples: Float32Array) => void;
  /**
   * Called when the server signals `{type:"interrupted"}`. Parent should
   * flush its playback worklet so queued Aria-audio drops immediately.
   */
  onInterrupted?: () => void;
}

/**
 * Lazy AudioContext + mic worklet bootstrap. We hold these in module-scope
 * refs so opening/closing the overlay doesn't churn the AudioContext (which
 * has a non-trivial startup cost and a one-shot user-gesture requirement on
 * iOS Safari — see docs § Mobile Safari constraints).
 */
interface MicResources {
  ctx: AudioContext;
  stream: MediaStream;
  source: MediaStreamAudioSourceNode;
  node: AudioWorkletNode;
}

async function bootstrapMic(
  onPcm: (samples: Int16Array) => void,
): Promise<MicResources> {
  const ctx = new AudioContext();
  // Resume in case it autostarted in 'suspended' (Chrome's autoplay policy).
  if (ctx.state === 'suspended') {
    try {
      await ctx.resume();
    } catch {
      // ignore — the worklet will simply produce no output until resumed
    }
  }
  // The capture worklet is served as a static asset from `/public`
  // (`public/capture-worklet.js`). An AudioWorklet module must be plain
  // browser JS loaded from a real URL — bundling a `.ts` worklet via
  // `new URL(..., import.meta.url)` does not resolve reliably under
  // Turbopack (it failed with "Unable to load a worklet's module").
  await ctx.audioWorklet.addModule('/capture-worklet.js');

  const stream = await navigator.mediaDevices.getUserMedia({
    audio: {
      channelCount: 1,
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true,
    },
    video: false,
  });
  const source = ctx.createMediaStreamSource(stream);
  const node = new AudioWorkletNode(ctx, 'capture-processor');
  node.port.onmessage = (event: MessageEvent<{ type: string; samples: Int16Array }>) => {
    if (event.data?.type === 'pcm16' && event.data.samples) {
      onPcm(event.data.samples);
    }
  };
  source.connect(node);
  // The worklet doesn't write to its output — we don't connect it to the
  // destination so the user doesn't hear themselves.
  return { ctx, stream, source, node };
}

function teardownMic(res: MicResources | null): void {
  if (!res) return;
  try {
    res.node.disconnect();
  } catch {
    // ignore
  }
  try {
    res.source.disconnect();
  } catch {
    // ignore
  }
  res.stream.getTracks().forEach((t) => {
    try {
      t.stop();
    } catch {
      // ignore
    }
  });
  // Closing the context is intentionally best-effort — Firefox can throw
  // if the context is already in 'closed' state from a prior teardown.
  try {
    void res.ctx.close();
  } catch {
    // ignore
  }
}

function hintForState(state: GeminiLiveState): string {
  switch (state) {
    case 'idle':
      return "Tap when you're ready";
    case 'connecting':
      return 'Connecting…';
    case 'listening':
      return "I'm listening…";
    case 'speaking':
      return 'Aria speaking';
    case 'error':
      return "Something glitched — try again";
    case 'closed':
      return 'Tap to start';
    default:
      return "I'm listening…";
  }
}

export function VoiceMode({
  active,
  onCancel,
  onSubmit,
  sessionId,
  topic,
  onAudioChunk,
  onInterrupted,
}: VoiceModeProps) {
  const [transcript, setTranscript] = useState('');
  const micRef = useRef<MicResources | null>(null);

  const handleTranscript = useCallback((text: string) => {
    // Gemini Live emits `input_transcription` as streaming fragments that
    // already carry their own leading spaces/punctuation — concatenate raw
    // so the accumulated turn reads naturally (joining with extra spaces
    // would break mid-word splits like " phys" + "ics").
    setTranscript((prev) => prev + text);
  }, []);

  const live = useGeminiLive({
    sessionId,
    topic,
    onTranscript: handleTranscript,
    onInterrupted,
    onTurnComplete: () => {
      // Visual reset handled by `state` flipping back to 'listening'.
    },
  });

  // Fan inbound model audio (24 kHz Float32) out to the parent's playback worklet.
  useEffect(() => {
    if (!onAudioChunk) return undefined;
    return live.audioChunk$(onAudioChunk);
  }, [live, onAudioChunk]);

  // Open / close lifecycle. `active` is the single source of truth from the
  // parent shell — we open the WS + mic when it's true and tear both down
  // immediately on close. No auto-reconnect.
  useEffect(() => {
    if (!active) {
      teardownMic(micRef.current);
      micRef.current = null;
      live.stop();
      setTranscript('');
      return;
    }

    let cancelled = false;
    (async () => {
      await live.start();
      if (cancelled) return;
      try {
        micRef.current = await bootstrapMic((pcm) => {
          // The capture worklet transfers Int16 buffers; forward straight through.
          live.pushAudio(pcm);
        });
      } catch (e) {
        // getUserMedia denied / unavailable, or the capture worklet failed
        // to load — the overlay still works as a visual surface, but no
        // audio is sent. Surface the cause instead of failing silently.
        console.error('[voice] microphone capture failed to start:', e);
      }
    })();

    return () => {
      cancelled = true;
      teardownMic(micRef.current);
      micRef.current = null;
      live.stop();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active]);

  const listening = live.state === 'listening' || live.state === 'speaking';

  const finish = () => {
    const text = transcript.trim();
    // Hand the transcript to the parent for the QA → text-fallback handoff.
    // Note: with a real Gemini Live session the audio answer is already
    // playing through the worklet, so this is primarily for the case where
    // the student wants a written/diagrammed reply.
    if (text.length > 0) {
      setTimeout(() => onSubmit(text), 200);
    } else {
      onCancel();
    }
  };

  const cancel = () => {
    // Force the model to yield (in case it's mid-response) and close.
    live.interrupt();
    live.stop();
    onCancel();
  };

  return (
    <div className={cn('vm-ov', active && 'active')}>
      <div className="vm-dim" onClick={cancel} role="presentation" />
      <div className="vm-stage">
        <div className="vm-hint">{hintForState(live.state)}</div>

        <div className={cn('vm-mic-orb', listening && 'live')}>
          <Waveform active={listening} />
          <div className="vm-mic-core">
            <Icon name="mic" size={32} />
          </div>
          <span className="vm-ring r1" />
          <span className="vm-ring r2" />
          <span className="vm-ring r3" />
        </div>

        <div className="vm-transcript">
          {transcript || (
            <span className="vm-placeholder">Say anything — I&apos;ll draw the answer.</span>
          )}
          {listening && transcript && <span className="vm-cursor" />}
        </div>

        <div className="vm-actions">
          <button type="button" className="vm-btn vm-cancel" onClick={cancel}>
            <Icon name="close" size={16} /> Cancel
          </button>
          <button
            type="button"
            className="vm-btn vm-send"
            onClick={finish}
            disabled={!transcript.trim()}
          >
            <Icon name="send" size={16} /> Ask Aria
          </button>
        </div>
      </div>
    </div>
  );
}
