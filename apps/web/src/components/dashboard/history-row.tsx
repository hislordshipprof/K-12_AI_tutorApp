'use client';

import { useRouter } from 'next/navigation';

import { resolveClassroomTopicPath } from '@/lib/api';
import { cn } from '@/lib/utils';

export interface HistoryRowData {
  t: string;
  s: string;
  d: string;
  /** Optional — `undefined` when the user hasn't taken the quiz for this lesson yet. */
  score?: number;
  status?: string;
  /** Topic id — drives "Replay" back into the real lesson. */
  topicId?: string;
}

export interface HistoryRowProps {
  row: HistoryRowData;
}

/**
 * One lesson-history row — chalk thumbnail, title/meta, date, score, replay.
 *
 * Ported from `.hist-row` in the prototype.
 */
export function HistoryRow({ row }: HistoryRowProps) {
  const router = useRouter();
  // Replay routes to the row's real topic UUID. When a legacy row carries
  // no `topicId` we resolve the first real curriculum topic rather than the
  // old prototype slug (which has no `topics` row → session FK failure).
  const goto = async () => {
    if (row.topicId) {
      router.push(`/classroom/${row.topicId}`);
      return;
    }
    const resolved = await resolveClassroomTopicPath();
    if (resolved) router.push(resolved);
  };
  const hasScore = typeof row.score === 'number';
  const isLow = hasScore && row.score! < 75;

  return (
    <div
      onClick={goto}
      className={cn(
        'mb-2 grid cursor-pointer items-center gap-[18px] rounded-[14px] border border-border bg-white px-5 py-4 transition-all',
        'hover:-translate-y-px hover:shadow-md',
      )}
      style={{ gridTemplateColumns: '80px 1fr auto auto auto' }}
    >
      <div className="relative h-[50px] w-20 overflow-hidden rounded-lg bg-board">
        <svg
          viewBox="0 0 80 50"
          preserveAspectRatio="none"
          className="absolute inset-0 h-full w-full"
        >
          <path
            d="M2,30 Q12,8 22,30 T42,30 T62,30 T78,30"
            fill="none"
            stroke="#A8C4E8"
            strokeWidth="1.5"
            opacity={hasScore ? row.score! / 100 : 0.4}
          />
          <line
            x1="2"
            y1="30"
            x2="78"
            y2="30"
            stroke="rgba(255,255,255,.18)"
            strokeWidth=".5"
            strokeDasharray="3,2"
          />
        </svg>
      </div>
      <div>
        <div className="text-sm font-semibold tracking-[-0.005em]">{row.t}</div>
        <div className="mt-0.5 text-xs text-ink-3">
          {row.s}
          {row.status ? ` · ${row.status}` : ''}
        </div>
      </div>
      <div className="min-w-[80px] text-right font-mono text-xs text-ink-3">
        {row.d}
      </div>
      <div
        className={cn(
          'flex items-center gap-1.5 rounded-lg px-3 py-[5px] text-[13px] font-bold',
          !hasScore
            ? 'bg-paper-2 text-ink-3'
            : isLow
              ? 'bg-coral-soft text-[#A1452B]'
              : 'bg-mint-soft text-[#1C7A47]',
        )}
      >
        {hasScore ? `${row.score}%` : '—'}
      </div>
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          void goto();
        }}
        className="rounded-[9px] bg-ink px-3.5 py-[7px] text-xs font-semibold text-white"
      >
        Replay
      </button>
    </div>
  );
}
