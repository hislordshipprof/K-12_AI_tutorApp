'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import { AriaMascot } from '@/components/aria/aria-mascot';
import { Icon } from '@/components/aria/icon';
import { MathContent } from '@/components/aria/math-content';
import { QASceneCanvas, type QAScene } from '@/components/classroom/qa-scene-canvas';
import { streamSSE } from '@/lib/sse';
import { cn } from '@/lib/utils';

type Stage = 'input' | 'asked' | 'answered';

interface QAOverlayProps {
  active: boolean;
  onClose: () => void;
  /** When set (e.g. from voice mode), auto-ask the given question. */
  initialQ: string | null;
  sessionId: string | null;
}

interface SSEPayload {
  type: 'token' | 'done' | 'error' | 'scene';
  content?: string;
  message?: string;
  /** Sent once, before the first token, when the question matches a scene. */
  scene?: QAScene;
}

const CHIPS = [
  "What's amplitude again?",
  'How is wavelength different from period?',
  'Can you show me v = f · λ on the board?',
  'What units is frequency in?',
];

/**
 * "Raise hand" overlay — student asks Aria a question; Aria streams a
 * Socratic answer over SSE while a keyword-matched chalk diagram animates
 * onto the board (the same scene engine the lesson steps use).
 *
 * The SSE call POSTs to `/v1/sessions/{sessionId}/qa`. When `sessionId`
 * is null (offline / unauthenticated) we still surface the input UI but
 * skip the stream and show a placeholder.
 */
export function QAOverlay({ active, onClose, initialQ, sessionId }: QAOverlayProps) {
  const [stage, setStage] = useState<Stage>('input');
  const [q, setQ] = useState('');
  const [scene, setScene] = useState<QAScene | null>(null);
  const [answer, setAnswer] = useState('');
  const [streaming, setStreaming] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  /**
   * Debounce timer for the "type-to-cancel" UX. When the student edits the
   * textarea while a stream is in-flight, we wait 150ms of quiet before
   * aborting — that way a single accidental keystroke doesn't nuke the
   * answer, but deliberate typing of a follow-up does. See
   * docs/interruption-architecture.md § Modality 3.
   */
  const autoAbortTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  /** Latest value of `streaming` — read inside ref'd callbacks without re-binding. */
  const streamingRef = useRef(streaming);
  useEffect(() => {
    streamingRef.current = streaming;
  }, [streaming]);

  /** Hard abort: cancel in-flight stream + reset the streaming flag. */
  const stopStreaming = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setStreaming(false);
    if (autoAbortTimerRef.current) {
      clearTimeout(autoAbortTimerRef.current);
      autoAbortTimerRef.current = null;
    }
  }, []);

  // Reset state whenever overlay opens/closes.
  useEffect(() => {
    if (!active) {
      setStage('input');
      setQ('');
      setScene(null);
      setAnswer('');
      setStreaming(false);
      abortRef.current?.abort();
      abortRef.current = null;
      if (autoAbortTimerRef.current) {
        clearTimeout(autoAbortTimerRef.current);
        autoAbortTimerRef.current = null;
      }
    }
  }, [active]);

  // Cleanup any pending debounce timer on unmount.
  useEffect(() => {
    return () => {
      if (autoAbortTimerRef.current) clearTimeout(autoAbortTimerRef.current);
    };
  }, []);

  // Auto-ask when launched via voice with an initial question.
  useEffect(() => {
    if (active && initialQ) {
      void ask(initialQ);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, initialQ]);

  const ask = async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed) return;
    setQ(trimmed);
    setScene(null);
    setStage('asked');
    setAnswer('');
    setStreaming(true);

    abortRef.current?.abort();
    const ctl = new AbortController();
    abortRef.current = ctl;

    // Drive the chalk-answer animation in tandem with the SSE stream.
    setTimeout(() => setStage('answered'), 600);

    if (!sessionId) {
      // No backend session — show a static fallback after the diagram animates.
      setTimeout(() => {
        setAnswer(
          "I'm still warming up — try asking again in a moment.",
        );
        setStreaming(false);
      }, 1200);
      return;
    }

    try {
      const iter = streamSSE<SSEPayload>(`/v1/sessions/${sessionId}/qa`, {
        json: { question: trimmed, source: 'text' },
        signal: ctl.signal,
      });
      for await (const ev of iter) {
        if (ev.type === 'scene' && ev.scene) {
          setScene(ev.scene);
        } else if (ev.type === 'token' && ev.content) {
          setAnswer((a) => a + ev.content);
        } else if (ev.type === 'done') {
          break;
        } else if (ev.type === 'error') {
          setAnswer((a) => (a ? a : `Sorry — I couldn't fetch that just now. (${ev.message ?? ''})`));
          break;
        }
      }
    } catch (e) {
      if ((e as { name?: string }).name !== 'AbortError') {
        setAnswer(
          (a) => a || "Hmm — I lost the connection. Try asking again in a sec.",
        );
      }
    } finally {
      setStreaming(false);
    }
  };

  return (
    <div className={cn('qa-ov', active && 'active')}>
      <div className="qa-dim" />
      <QASceneCanvas scene={scene} />

      {stage !== 'input' && (
        <div className="qa-q">
          <div className="qa-q-lbl">👋 You asked</div>
          <div className="qa-q-txt">&quot;{q}&quot;</div>
        </div>
      )}

      {stage === 'answered' && (
        <div className="qa-aria">
          <div className="qa-aria-hd">
            <AriaMascot size={28} speaking={streaming} />
            <span className="name">Prof. Aria · answering</span>
            {streaming && (
              // Visible only while a stream is in flight. Aborts the SSE
              // and keeps the overlay open so the student can immediately
              // type a follow-up. See docs § Modality 3.
              <button
                type="button"
                className="qa-stop"
                onClick={stopStreaming}
                aria-label="Stop generating"
                style={{
                  marginLeft: 'auto',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 6,
                  padding: '4px 10px',
                  fontSize: 12,
                  fontWeight: 600,
                  color: 'rgba(255,255,255,.9)',
                  background: 'rgba(255,255,255,.08)',
                  border: '1px solid rgba(255,255,255,.18)',
                  borderRadius: 999,
                  cursor: 'pointer',
                }}
              >
                <Icon name="close" size={12} /> Stop
              </button>
            )}
          </div>
          <div className="qa-aria-txt">
            {answer ? (
              // Aria's responses contain LaTeX-delimited math per the
              // SOCRATIC_RULES persona prompt — render through KaTeX so
              // $T = 1/f$ etc. typeset properly instead of leaking the $.
              <MathContent html={answer} />
            ) : streaming ? (
              <em>Thinking…</em>
            ) : (
              <em>Ready when you are.</em>
            )}
          </div>
        </div>
      )}

      {stage === 'input' && (
        <div className="qa-chips">
          {CHIPS.map((c) => (
            <button key={c} type="button" className="qa-chip" onClick={() => void ask(c)}>
              {c}
            </button>
          ))}
        </div>
      )}

      <div className="qa-bar">
        {stage === 'input' ? (
          <>
            <textarea
              className="qa-ta"
              placeholder="Ask Prof. Aria anything…"
              rows={1}
              value={q}
              onChange={(e) => {
                setQ(e.target.value);
                // Auto-abort: if a stream is still in-flight when the
                // student starts typing a follow-up, debounce-cancel it
                // after 150 ms of typing. Lets the user correct mid-answer
                // without explicitly clicking Stop.
                if (streamingRef.current) {
                  if (autoAbortTimerRef.current) clearTimeout(autoAbortTimerRef.current);
                  autoAbortTimerRef.current = setTimeout(() => {
                    autoAbortTimerRef.current = null;
                    if (streamingRef.current) stopStreaming();
                  }, 150);
                }
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey && q.trim()) {
                  e.preventDefault();
                  void ask(q);
                }
              }}
              autoFocus
            />
            <button
              type="button"
              className="qa-send"
              disabled={!q.trim()}
              onClick={() => q.trim() && void ask(q)}
              style={{ opacity: q.trim() ? 1 : 0.5 }}
            >
              <Icon name="send" size={20} />
            </button>
            <button type="button" className="qa-resume" onClick={onClose}>
              <Icon name="play" size={14} /> Resume
            </button>
          </>
        ) : (
          <>
            <button
              type="button"
              className="qa-resume"
              onClick={() => {
                abortRef.current?.abort();
                setStage('input');
                setQ('');
                setAnswer('');
                setScene(null);
              }}
              style={{ flex: 1, justifyContent: 'center' }}
            >
              Ask another
            </button>
            <button
              type="button"
              className="qa-send"
              style={{ width: 'auto', padding: '0 22px' }}
              onClick={onClose}
            >
              <Icon name="play" size={16} />
              <span style={{ marginLeft: 8, fontSize: 14, fontWeight: 700 }}>Got it · Resume</span>
            </button>
          </>
        )}
      </div>
    </div>
  );
}
