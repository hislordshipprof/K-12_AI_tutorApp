'use client';

import { useRouter } from 'next/navigation';
import { useMemo } from 'react';

import { Icon } from '@/components/aria/icon';

interface CompleteScreenProps {
  sessionId: string;
}

interface ConfettiPiece {
  i: number;
  l: number;
  d: number;
  r: number;
  c: string;
  s: number;
  dur: number;
}

const COLORS = ['#FFC857', '#FF7A59', '#5B5BE5', '#34C97A', '#A78BFA'];

/**
 * Lesson-complete celebration: trophy + scores + CTAs + animated confetti.
 *
 * Confetti pieces are deterministic per render (no SSR mismatch) — we
 * still seed positions with Math.random because the component is client-only.
 */
export function CompleteScreen({ sessionId }: CompleteScreenProps) {
  const router = useRouter();

  // Confetti shape array is fine to recompute on each mount — there are
  // only 40 pieces and the CSS animation handles the visual loop.
  const pieces = useMemo<ConfettiPiece[]>(
    () =>
      Array.from({ length: 40 }, (_, i) => ({
        i,
        l: Math.random() * 100,
        d: Math.random() * 3,
        r: Math.random() * 360,
        c: COLORS[i % COLORS.length] ?? '#FFC857',
        s: 6 + Math.random() * 6,
        dur: 4 + Math.random() * 3,
      })),
    [],
  );

  // sessionId is reserved for future "share / replay" wiring.
  void sessionId;

  return (
    <div className="screen complete min-h-screen overflow-y-auto">
      <div className="complete-confetti" aria-hidden>
        {pieces.map((p) => (
          <div
            key={p.i}
            style={{
              position: 'absolute',
              left: `${p.l}%`,
              top: '-20px',
              width: p.s,
              height: p.s * 1.6,
              background: p.c,
              transform: `rotate(${p.r}deg)`,
              animation: `confettiFall ${p.dur}s linear ${p.d}s infinite`,
            }}
          />
        ))}
      </div>

      <div className="complete-wrap">
        <div className="complete-trophy">🏆</div>
        <h1 className="complete-ttl">
          Lesson <em>complete!</em>
        </h1>
        <p className="complete-sub">
          You mastered Wave Properties &amp; Anatomy. That&apos;s <b>+1 topic</b> toward your AP-5
          goal. Aria has notes saved for you.
        </p>
        <div className="complete-scores">
          <div className="cs">
            <div className="cs-v gold">92%</div>
            <div className="cs-l">Quiz score</div>
          </div>
          <div className="cs">
            <div className="cs-v mint">18m</div>
            <div className="cs-l">Lesson time</div>
          </div>
          <div className="cs">
            <div className="cs-v indigo">3</div>
            <div className="cs-l">Questions asked</div>
          </div>
        </div>
        <div className="complete-btns">
          <button
            type="button"
            className="btn btn-primary lg"
            onClick={() => router.push('/classroom/wave-speed-medium')}
          >
            <Icon name="arrow" size={16} /> Next: Wave Speed &amp; Medium
          </button>
          <button
            type="button"
            className="btn btn-ghost lg"
            onClick={() => router.push('/')}
          >
            Back to dashboard
          </button>
        </div>
        <div
          style={{
            marginTop: 32,
            display: 'flex',
            gap: 8,
            justifyContent: 'center',
            alignItems: 'center',
            fontSize: 13,
            color: 'var(--ink-3)',
          }}
        >
          <span>🔥 5 day streak →</span>
          <b style={{ color: 'var(--ink)' }}>6 day streak</b>
        </div>
      </div>
    </div>
  );
}
