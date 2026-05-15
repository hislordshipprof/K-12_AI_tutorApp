'use client';

import { useQuery } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import { useMemo } from 'react';

import { Icon } from '@/components/aria/icon';
import { useMe } from '@/hooks/use-me';
import { api } from '@/lib/api';

interface CompleteScreenProps {
  /** Route param — in practice the topic id the lesson/quiz just finished. */
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

interface TopicDto {
  id: string;
  name: string;
}

interface HistoryRowApi {
  topic_id: string | null;
  duration_min: number | null;
  score_pct: number | null;
}

const COLORS = ['#FFC857', '#FF7A59', '#5B5BE5', '#34C97A', '#A78BFA'];

/**
 * Lesson-complete celebration: trophy + real scores + CTAs + confetti.
 *
 * The route param is the topic id. We pull the topic name, the user's
 * per-topic quiz score + time-spent (from /v1/history), and the streak
 * (from /v1/me) — no fabricated numbers.
 */
export function CompleteScreen({ sessionId }: CompleteScreenProps) {
  const router = useRouter();
  const topicId = sessionId;
  const { data: me } = useMe();

  const { data: topic } = useQuery<TopicDto | null>({
    queryKey: ['topic', topicId],
    queryFn: async () => {
      try {
        return await api<TopicDto>(`/v1/topics/${topicId}`);
      } catch {
        return null;
      }
    },
    staleTime: 60_000,
  });

  const { data: historyRow } = useQuery<HistoryRowApi | null>({
    queryKey: ['history-row', topicId],
    queryFn: async () => {
      try {
        const rows = await api<HistoryRowApi[]>('/v1/history');
        return rows.find((r) => r.topic_id === topicId) ?? null;
      } catch {
        return null;
      }
    },
    staleTime: 30_000,
  });

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

  const topicName = topic?.name ?? 'this lesson';
  const scorePct = historyRow?.score_pct ?? null;
  const durationMin = historyRow?.duration_min ?? null;
  const streak = me?.streak_days ?? 0;

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
          You worked through <b>{topicName}</b>. Aria has notes saved for you.
        </p>
        <div className="complete-scores">
          <div className="cs">
            <div className="cs-v gold">{scorePct != null ? `${scorePct}%` : '—'}</div>
            <div className="cs-l">Quiz score</div>
          </div>
          <div className="cs">
            <div className="cs-v mint">{durationMin != null ? `${durationMin}m` : '—'}</div>
            <div className="cs-l">Lesson time</div>
          </div>
          <div className="cs">
            <div className="cs-v indigo">{streak}</div>
            <div className="cs-l">Day streak</div>
          </div>
        </div>
        <div className="complete-btns">
          <button
            type="button"
            className="btn btn-primary lg"
            onClick={() => router.push('/dashboard')}
          >
            <Icon name="arrow" size={16} /> Choose your next lesson
          </button>
          <button
            type="button"
            className="btn btn-ghost lg"
            onClick={() => router.push('/notes')}
          >
            Review your notes
          </button>
        </div>
      </div>
    </div>
  );
}
