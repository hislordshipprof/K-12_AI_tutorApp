'use client';

import { useEffect, useState } from 'react';

import { AriaMascot } from '@/components/aria/aria-mascot';
import { Icon } from '@/components/aria/icon';
import { MathContent } from '@/components/aria/math-content';
import { api, ApiError } from '@/lib/api';
import { cn } from '@/lib/utils';

interface QuizMePopProps {
  active: boolean;
  sessionId: string | null;
  onClose: () => void;
}

interface QuizQuestionDto {
  idx: number;
  prompt: string;
  choices: string[];
  correct_idx: number | null;
  explanation: string | null;
}

interface QuizAttemptDto {
  id: string;
  correct: boolean | null;
  correct_idx: number | null;
  explanation: string | null;
}

const LETTERS = ['A', 'B', 'C', 'D'];

/**
 * Single-question quiz interrupt. Fetches a real DB-backed question for
 * the current session's topic, posts the attempt for scoring, then
 * renders Aria's server-side explanation.
 *
 * Empty state (HTTP 404 with `code: "NO_QUESTIONS"`) renders a friendly
 * fallback rather than a generic error.
 */
export function QuizMePop({ active, sessionId, onClose }: QuizMePopProps) {
  const [question, setQuestion] = useState<QuizQuestionDto | null>(null);
  const [loadState, setLoadState] = useState<
    'idle' | 'loading' | 'ready' | 'empty' | 'error'
  >('idle');
  const [picked, setPicked] = useState<number | null>(null);
  const [reveal, setReveal] = useState<QuizAttemptDto | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // Reset whenever the overlay closes — fresh fetch on next open.
  useEffect(() => {
    if (!active) {
      setQuestion(null);
      setLoadState('idle');
      setPicked(null);
      setReveal(null);
      setSubmitting(false);
    }
  }, [active]);

  // Fetch a question whenever the overlay opens.
  useEffect(() => {
    if (!active || !sessionId) return;
    let cancelled = false;
    setLoadState('loading');
    api<QuizQuestionDto>(`/v1/sessions/${sessionId}/quiz`)
      .then((q) => {
        if (cancelled) return;
        setQuestion(q);
        setLoadState('ready');
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 404) {
          setLoadState('empty');
        } else {
          setLoadState('error');
        }
      });
    return () => {
      cancelled = true;
    };
  }, [active, sessionId]);

  async function handlePick(i: number) {
    if (reveal || submitting || !sessionId || !question) return;
    setPicked(i);
    setSubmitting(true);
    try {
      const result = await api<QuizAttemptDto>(
        `/v1/sessions/${sessionId}/quiz/attempt`,
        {
          method: 'POST',
          json: { question_idx: question.idx, picked_idx: i },
        },
      );
      setReveal(result);
    } catch {
      // Surface as an unrecoverable error state — student can close + retry.
      setLoadState('error');
    } finally {
      setSubmitting(false);
    }
  }

  function resetForNext() {
    setPicked(null);
    setReveal(null);
    // Force a fresh question fetch.
    setLoadState('loading');
    if (!sessionId) return;
    api<QuizQuestionDto>(`/v1/sessions/${sessionId}/quiz`)
      .then((q) => {
        setQuestion(q);
        setLoadState('ready');
      })
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 404) {
          setLoadState('empty');
        } else {
          setLoadState('error');
        }
      });
  }

  const correctIdx = reveal?.correct_idx ?? null;
  const isCorrect = reveal?.correct === true;

  return (
    <div className={cn('qmp-ov', active && 'active')}>
      <div className="qmp-dim" onClick={onClose} role="presentation" />
      <div className="qmp-card">
        <div className="qmp-hd">
          <div className="qmp-eyebrow">
            <span style={{ color: 'var(--amber)' }}>⚡</span> Quick check · 1 question
          </div>
          <button type="button" className="qmp-close" onClick={onClose}>
            <Icon name="close" size={14} />
          </button>
        </div>

        {loadState === 'loading' && (
          <div className="qmp-q" style={{ opacity: 0.6 }}>
            Loading a question…
          </div>
        )}

        {loadState === 'empty' && (
          <div className="qmp-q">
            No quiz for this topic yet. Try asking Aria a question instead — she can dig into
            any concept you want to test.
          </div>
        )}

        {loadState === 'error' && (
          <div className="qmp-q">
            Couldn&apos;t load a question right now. Close this and try again in a moment.
          </div>
        )}

        {loadState === 'ready' && question && (
          <>
            <div className="qmp-q">
              <MathContent html={question.prompt} />
            </div>
            <div className="qmp-opts">
              {question.choices.map((t, i) => {
                let cls = '';
                if (reveal) {
                  if (i === correctIdx) cls = 'right';
                  else if (picked === i) cls = 'wrong';
                } else if (picked === i) {
                  cls = 'selected';
                }
                return (
                  <button
                    key={i}
                    type="button"
                    className={cn('qmp-opt', cls)}
                    onClick={() => handlePick(i)}
                    disabled={submitting || !!reveal}
                  >
                    <span className="qmp-ltr">{LETTERS[i]}</span>
                    <span className="qmp-text">
                      <MathContent html={t} />
                    </span>
                  </button>
                );
              })}
            </div>
            {reveal && (
              <div className="qmp-fb">
                <AriaMascot size={28} />
                <div className="qmp-fb-text">
                  <b>{isCorrect ? 'Yes!' : 'Not quite.'}</b>{' '}
                  {reveal.explanation ? (
                    <MathContent html={reveal.explanation} />
                  ) : isCorrect ? (
                    <span>Nice work.</span>
                  ) : (
                    <span>Walk it back and try one more.</span>
                  )}
                </div>
              </div>
            )}
          </>
        )}

        <div className="qmp-actions">
          <button
            type="button"
            className="btn btn-ghost sm"
            onClick={onClose}
            style={{ borderColor: 'rgba(255,255,255,.16)', color: 'rgba(255,255,255,.7)' }}
          >
            Back to lesson
          </button>
          {reveal && (
            <button
              type="button"
              className="btn btn-amber sm"
              onClick={resetForNext}
            >
              One more →
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
