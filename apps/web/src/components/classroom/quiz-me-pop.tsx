'use client';

import { useEffect, useState } from 'react';

import { AriaMascot } from '@/components/aria/aria-mascot';
import { Icon } from '@/components/aria/icon';
import { cn } from '@/lib/utils';

interface QuizMePopProps {
  active: boolean;
  onClose: () => void;
}

const OPTIONS = [
  'It travels in a straight line forever.',
  'Its energy doubles every cycle.',
  'It transfers energy without moving the medium permanently.',
  'It needs a vacuum to propagate.',
];
const CORRECT = 2;
const LETTERS = ['A', 'B', 'C', 'D'];

/**
 * Single-question quiz interrupt. Local-only (no backend call yet) —
 * the prototype-equivalent UX of "quick check" mid-lesson.
 */
export function QuizMePop({ active, onClose }: QuizMePopProps) {
  const [picked, setPicked] = useState<number | null>(null);
  const [revealed, setRevealed] = useState(false);

  useEffect(() => {
    if (!active) {
      setPicked(null);
      setRevealed(false);
    }
  }, [active]);

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
        <div className="qmp-q">A wave does which of the following?</div>
        <div className="qmp-opts">
          {OPTIONS.map((t, i) => {
            let cls = '';
            if (revealed) {
              if (i === CORRECT) cls = 'right';
              else if (picked === i) cls = 'wrong';
            } else if (picked === i) {
              cls = 'selected';
            }
            return (
              <button
                key={i}
                type="button"
                className={cn('qmp-opt', cls)}
                onClick={() => {
                  if (revealed) return;
                  setPicked(i);
                  setTimeout(() => setRevealed(true), 350);
                }}
              >
                <span className="qmp-ltr">{LETTERS[i]}</span>
                <span className="qmp-text">{t}</span>
              </button>
            );
          })}
        </div>
        {revealed && (
          <div className="qmp-fb">
            <AriaMascot size={28} />
            <div className="qmp-fb-text">
              {picked === CORRECT ? (
                <>
                  <b>Yes!</b> Energy transfer without permanent displacement of the medium —
                  that&apos;s the whole point of a wave.
                </>
              ) : (
                <>
                  <b>Not quite.</b> Walk it back: think about what actually moves when a wave
                  passes by. Try again or keep watching.
                </>
              )}
            </div>
          </div>
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
          {revealed && (
            <button
              type="button"
              className="btn btn-amber sm"
              onClick={() => {
                setPicked(null);
                setRevealed(false);
              }}
            >
              One more →
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
