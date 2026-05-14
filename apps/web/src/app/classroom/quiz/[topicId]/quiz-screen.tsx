'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';

import { AriaMascot } from '@/components/aria/aria-mascot';
import { Icon } from '@/components/aria/icon';
import { api } from '@/lib/api';
import { cn } from '@/lib/utils';

interface QuizScreenProps {
  topicId: string;
}

interface QuizOption {
  ltr: string;
  t: string;
}

const OPTIONS: QuizOption[] = [
  { ltr: 'A', t: '4 seconds' },
  { ltr: 'B', t: '0.25 seconds' },
  { ltr: 'C', t: '8 seconds' },
  { ltr: 'D', t: '0.5 seconds' },
];
const CORRECT = 1;

/**
 * Single-question knowledge check (the prototype's "Question 2 of 3").
 *
 * Selecting an answer reveals feedback after a short delay; the "Next"
 * button is gated until feedback is shown. We POST the attempt to the
 * backend best-effort but don't block the UI on the result.
 */
export function QuizScreen({ topicId }: QuizScreenProps) {
  const router = useRouter();
  const [picked, setPicked] = useState<number | null>(null);
  const [showFb, setShowFb] = useState(false);

  const onPick = (i: number) => {
    if (showFb) return;
    setPicked(i);
    setTimeout(() => setShowFb(true), 350);
    // Fire-and-forget — the backend is stubbed for now.
    api(`/v1/quiz/${topicId}/attempt`, {
      method: 'POST',
      json: { question_idx: 1, picked_idx: i },
    }).catch(() => undefined);
  };

  const next = () => {
    // Once we have a real session id this becomes the actual session.
    // For now route to the topic slug so the completion screen has *something* to display.
    router.push(`/classroom/complete/${topicId}`);
  };

  return (
    <div className="screen min-h-screen overflow-y-auto bg-paper">
      <div className="quiz-wrap">
        <div className="quiz-hd">
          <div className="quiz-ic">
            <Icon name="sparkle" size={22} />
          </div>
          <div>
            <div className="quiz-ttl">Knowledge check</div>
            <div className="quiz-sub">Wave Properties &amp; Anatomy · 3 questions · ~5 min</div>
          </div>
        </div>
        <div className="quiz-prog">
          <div className="quiz-pseg done" />
          <div className="quiz-pseg cur" />
          <div className="quiz-pseg" />
        </div>

        <div className="q-card">
          <span className="q-num">Question 2 of 3</span>
          <div className="q-text">
            A wave has a frequency of{' '}
            <span style={{ background: 'var(--amber-soft)', padding: '0 6px', borderRadius: 4 }}>
              4 Hz
            </span>
            . What is its{' '}
            <em style={{ fontStyle: 'italic', color: 'var(--indigo)' }}>period</em>?
          </div>
          <div className="q-opts">
            {OPTIONS.map((o, i) => {
              let cls = '';
              if (showFb) {
                if (i === CORRECT) cls = 'correct';
                else if (picked === i) cls = 'wrong';
              } else if (picked === i) {
                cls = 'selected';
              }
              return (
                <button
                  key={i}
                  type="button"
                  className={cn('q-opt', cls)}
                  onClick={() => onPick(i)}
                >
                  <div className="q-letter">{o.ltr}</div>
                  <div className="q-opt-text">{o.t}</div>
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
                  {picked === CORRECT ? (
                    <>
                      <b>Nailed it.</b> T = 1/f = 1/4 = 0.25s. Remember: frequency and period are
                      reciprocals — they always move opposite directions.
                    </>
                  ) : (
                    <>
                      <b>Close — but no.</b> The relationship is T = 1/f. So 1 ÷ 4 = 0.25s. Period
                      and frequency are always reciprocals.
                    </>
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
