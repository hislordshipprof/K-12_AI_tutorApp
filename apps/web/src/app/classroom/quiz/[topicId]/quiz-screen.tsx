'use client';

import { useRouter, useSearchParams } from 'next/navigation';
import { useEffect, useState } from 'react';

import { AriaMascot } from '@/components/aria/aria-mascot';
import { Icon } from '@/components/aria/icon';
import { MathContent } from '@/components/aria/math-content';
import { api, ApiError } from '@/lib/api';
import { cn } from '@/lib/utils';

interface QuizScreenProps {
  topicId: string;
}

interface FetchedQuestion {
  idx: number;
  prompt: string;
  choices: string[];
}

interface AttemptResult {
  correct: boolean | null;
  correct_idx: number | null;
  explanation: string | null;
}

/**
 * End-of-lesson "Knowledge check" screen.
 *
 * When a `?session=<id>` query param is present (the classroom-shell passes
 * it on the "Quiz me" button), we fetch a real DB-backed question via
 * `/v1/sessions/{id}/quiz` and score against the real answer key. Without
 * a session id (legacy / Playwright fixture deep-links) we fall back to
 * the prototype's hardcoded "wave period" question so the screen still
 * renders something sensible.
 */
export function QuizScreen({ topicId }: QuizScreenProps) {
  const router = useRouter();
  const search = useSearchParams();
  const sessionId = search.get('session');

  // Hardcoded fallback (matches the prototype + Playwright assertions).
  const FALLBACK = {
    prompt: 'A wave has a frequency of 4 Hz. What is its period?',
    choices: ['4 seconds', '0.25 seconds', '8 seconds', '0.5 seconds'],
    correctIdx: 1,
    correctExplanation:
      '<b>Nailed it.</b> $T = 1/f = 1/4 = 0.25$s. Remember: frequency and period are reciprocals — they always move opposite directions.',
    wrongExplanation:
      '<b>Close — but no.</b> The relationship is $T = 1/f$. So $1 \\div 4 = 0.25$s. Period and frequency are always reciprocals.',
  };

  const [question, setQuestion] = useState<FetchedQuestion | null>(null);
  const [mode, setMode] = useState<'live' | 'fallback'>('fallback');
  const [picked, setPicked] = useState<number | null>(null);
  const [showFb, setShowFb] = useState(false);
  const [reveal, setReveal] = useState<AttemptResult | null>(null);

  // A session id gives the most precise route; without one we fetch a real
  // question for the topic itself. Only a genuine "no questions" / error
  // falls back to the prototype copy.
  const quizGetUrl = sessionId
    ? `/v1/sessions/${sessionId}/quiz`
    : `/v1/quiz/${topicId}`;
  const quizAttemptUrl = sessionId
    ? `/v1/sessions/${sessionId}/quiz/attempt`
    : `/v1/quiz/${topicId}/attempt`;

  useEffect(() => {
    let cancelled = false;
    api<FetchedQuestion>(quizGetUrl)
      .then((q) => {
        if (cancelled) return;
        setQuestion(q);
        setMode('live');
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        // 404 NO_QUESTIONS or anything else → fall back to prototype copy.
        if (err instanceof ApiError) {
          // Intentional swallow — the screen still renders the fallback.
        }
        setMode('fallback');
      });
    return () => {
      cancelled = true;
    };
  }, [quizGetUrl]);

  const onPick = async (i: number) => {
    if (showFb) return;
    setPicked(i);
    setTimeout(() => setShowFb(true), 350);

    if (mode === 'live' && question) {
      try {
        const result = await api<AttemptResult>(quizAttemptUrl, {
          method: 'POST',
          json: { question_idx: question.idx, picked_idx: i },
        });
        setReveal(result);
      } catch {
        // Keep the optimistic UI even if scoring fails.
      }
    } else {
      // Fallback mode still POSTs (mock api expects it) but ignores result.
      api(`/v1/quiz/${topicId}/attempt`, {
        method: 'POST',
        json: { question_idx: 1, picked_idx: i },
      }).catch(() => undefined);
    }
  };

  const next = () => router.push(`/classroom/complete/${topicId}`);

  // Pick which dataset drives the render.
  const prompt = mode === 'live' && question ? question.prompt : FALLBACK.prompt;
  const choices =
    mode === 'live' && question ? question.choices : FALLBACK.choices;
  const correctIdx =
    mode === 'live' ? reveal?.correct_idx ?? null : FALLBACK.correctIdx;
  const isCorrect =
    mode === 'live'
      ? reveal?.correct === true
      : picked === FALLBACK.correctIdx;
  const feedbackHtml =
    mode === 'live'
      ? reveal?.explanation ?? ''
      : isCorrect
        ? FALLBACK.correctExplanation
        : FALLBACK.wrongExplanation;

  return (
    <div className="screen min-h-screen overflow-y-auto bg-paper">
      <div className="quiz-wrap">
        <div className="quiz-hd">
          <div className="quiz-ic">
            <Icon name="sparkle" size={22} />
          </div>
          <div>
            <div className="quiz-ttl">Knowledge check</div>
            <div className="quiz-sub">
              {mode === 'live' ? 'Live question · scored by Aria' : 'Wave Properties & Anatomy · 3 questions · ~5 min'}
            </div>
          </div>
        </div>
        <div className="quiz-prog">
          <div className="quiz-pseg done" />
          <div className="quiz-pseg cur" />
          <div className="quiz-pseg" />
        </div>

        <div className="q-card">
          <span className="q-num">Question {(question?.idx ?? 1) + 1} of 3</span>
          <div className="q-text">
            {mode === 'live' ? <MathContent html={prompt} /> : (
              <>
                A wave has a frequency of{' '}
                <span style={{ background: 'var(--amber-soft)', padding: '0 6px', borderRadius: 4 }}>
                  4 Hz
                </span>
                . What is its{' '}
                <em style={{ fontStyle: 'italic', color: 'var(--indigo)' }}>period</em>?
              </>
            )}
          </div>
          <div className="q-opts">
            {choices.map((opt, i) => {
              let cls = '';
              if (showFb) {
                if (correctIdx !== null && i === correctIdx) cls = 'correct';
                else if (picked === i) cls = 'wrong';
              } else if (picked === i) {
                cls = 'selected';
              }
              const letter = ['A', 'B', 'C', 'D'][i] ?? '?';
              return (
                <button
                  key={i}
                  type="button"
                  className={cn('q-opt', cls)}
                  onClick={() => onPick(i)}
                >
                  <div className="q-letter">{letter}</div>
                  <div className="q-opt-text">
                    {mode === 'live' ? <MathContent html={opt} /> : opt}
                  </div>
                </button>
              );
            })}
          </div>
          {showFb && (
            <div className="q-fb">
              <div className="q-fb-av">
                <AriaMascot size={32} />
              </div>
              <div className="q-fb-body">
                <div className="q-fb-who">Prof. Aria</div>
                <div className="q-fb-txt">
                  {mode === 'live' && reveal ? (
                    <>
                      <b>{isCorrect ? 'Nailed it.' : 'Close — but no.'}</b>{' '}
                      {feedbackHtml ? <MathContent html={feedbackHtml} /> : null}
                    </>
                  ) : (
                    <MathContent html={feedbackHtml} />
                  )}
                </div>
              </div>
            </div>
          )}
        </div>

        <div className="q-nav">
          <button
            type="button"
            className="btn btn-ghost"
            onClick={() => router.push(`/classroom/${topicId}`)}
          >
            ← Back to lesson
          </button>
          <div style={{ display: 'flex', gap: 10 }}>
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() => {
                setPicked(null);
                setShowFb(false);
                setReveal(null);
              }}
            >
              Skip
            </button>
            <button
              type="button"
              className="btn btn-indigo"
              disabled={!showFb}
              style={{ opacity: showFb ? 1 : 0.5 }}
              onClick={next}
            >
              Next question <Icon name="arrow" size={16} />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
