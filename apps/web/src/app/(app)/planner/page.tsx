'use client';

import { useQuery } from '@tanstack/react-query';

import {
  WeekDayColumn,
  type WeekBlockColor,
  type WeekDay,
} from '@/components/dashboard/week-day-column';
import { useMe } from '@/hooks/use-me';
import { api } from '@/lib/api';

interface PlannerBlock {
  id?: string;
  date: string;          // ISO date "YYYY-MM-DD"
  start_time?: string | null;
  duration_min?: number | null;
  kind: 'lesson' | 'quiz' | 'flashcards' | 'office_hours' | 'rest';
  payload?: Record<string, unknown> | null;
  status?: 'planned' | 'done' | 'skipped';
}

interface PlannerWeek {
  week_start: string; // ISO Monday
  blocks: PlannerBlock[];
}

const DAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'] as const;

function addDays(iso: string, days: number): { iso: string; n: number } {
  const d = new Date(`${iso}T00:00:00`);
  d.setUTCDate(d.getUTCDate() + days);
  return { iso: d.toISOString().slice(0, 10), n: d.getUTCDate() };
}

function todayISODate(): string {
  return new Date().toISOString().slice(0, 10);
}

function colorFor(kind: PlannerBlock['kind'], status?: PlannerBlock['status']): WeekBlockColor {
  if (status === 'done') return 'mint done';
  switch (kind) {
    case 'lesson': return 'indigo';
    case 'quiz': return 'amber';
    case 'flashcards': return 'amber';
    case 'office_hours': return 'coral';
    case 'rest': return 'mint';
    default: return 'lav';
  }
}

function metaFor(b: PlannerBlock): string {
  const dur = b.duration_min ? `${b.duration_min}m` : '';
  const kind = b.kind.replace('_', ' ');
  return [dur, kind].filter(Boolean).join(' · ');
}

function titleFor(b: PlannerBlock): string {
  const title = (b.payload?.title as string | undefined) ?? '';
  return title || b.kind.replace('_', ' ');
}

export default function PlannerPage() {
  const { data: me } = useMe();

  const { data: week } = useQuery<PlannerWeek | null>({
    queryKey: ['planner-week'],
    queryFn: async () => {
      try {
        return await api<PlannerWeek>('/v1/planner/week');
      } catch {
        return null;
      }
    },
    staleTime: 30_000,
  });

  const today = todayISODate();
  const weekStart = week?.week_start ?? today;
  const days: WeekDay[] = DAY_LABELS.map((label, i) => {
    const { iso, n } = addDays(weekStart, i);
    const dayBlocks = (week?.blocks ?? []).filter((b) => b.date === iso);
    return {
      d: label,
      n,
      today: iso === today,
      blocks: dayBlocks.map((b) => ({
        c: colorFor(b.kind, b.status),
        t: titleFor(b),
        m: metaFor(b),
      })),
    };
  });

  const hasAnyBlock = days.some((d) => d.blocks.length > 0);

  return (
    <div className="bg-paper">
      {/* HEADER */}
      <div className="mx-auto flex max-w-[1180px] flex-wrap items-end justify-between gap-6 px-8 pb-6 pt-8">
        <div>
          <div className="font-display text-4xl font-bold leading-[1.05] tracking-[-0.03em]">
            Your week with Aria
          </div>
          <div className="mt-1.5 max-w-[480px] text-sm text-ink-3">
            A study plan built around your goal, pace, and energy. Tap any block
            to reschedule.
          </div>
        </div>
        <div className="flex gap-2.5">
          <button
            type="button"
            className="rounded-[10px] border-[1.5px] border-border-2 bg-transparent px-3.5 py-2 text-[13px] font-semibold text-ink transition-colors hover:bg-black/5"
          >
            ← Last week
          </button>
          <button
            type="button"
            className="rounded-[10px] border-[1.5px] border-border-2 bg-transparent px-3.5 py-2 text-[13px] font-semibold text-ink transition-colors hover:bg-black/5"
          >
            This week
          </button>
          <button
            type="button"
            className="rounded-[10px] bg-ink px-3.5 py-2 text-[13px] font-semibold text-white transition-all hover:-translate-y-px hover:bg-black"
          >
            Generate next →
          </button>
        </div>
      </div>

      {/* BODY */}
      <div className="mx-auto grid max-w-[1180px] grid-cols-1 gap-5 px-8 pb-20 lg:grid-cols-[1fr_280px]">
        <div>
          {!hasAnyBlock && (
            <div className="mb-4 rounded-2xl border border-dashed border-border bg-white px-6 py-8 text-center">
              <div className="text-base font-semibold text-ink">No plan for this week yet</div>
              <div className="mt-1 text-sm text-ink-3">
                Aria will draft a study plan once you complete your first lesson, or click <b>Generate next →</b> to start one now.
              </div>
            </div>
          )}
          <div className="grid grid-cols-7 gap-2">
            {days.map((day) => (
              <WeekDayColumn key={day.d} day={day} />
            ))}
          </div>
        </div>

        {/* SIDEBAR */}
        <div className="flex flex-col gap-3.5">
          <div className="rounded-[18px] border border-border bg-white p-5 shadow-sm">
            <div className="mb-3 font-display text-base font-bold tracking-[-0.015em]">
              Weekly stats
            </div>
            <div className="flex justify-between text-[13px]">
              <span className="text-ink-3">Topics done</span>
              <b className="tabular-nums">{me?.stats.topics_done ?? 0}</b>
            </div>
            <div className="mt-2 flex justify-between text-[13px]">
              <span className="text-ink-3">Time learned</span>
              <b className="tabular-nums">
                {me ? `${(me.stats.time_spent_min / 60).toFixed(1)}h` : '—'}
              </b>
            </div>
            <div className="mt-2 flex justify-between text-[13px]">
              <span className="text-ink-3">Quiz avg</span>
              <b className="tabular-nums">
                {me?.stats.quiz_avg_pct != null ? `${me.stats.quiz_avg_pct}%` : '—'}
              </b>
            </div>
            <div className="mt-2 flex justify-between text-[13px]">
              <span className="text-ink-3">Streak</span>
              <b className="tabular-nums">{me?.streak_days ?? 0} days 🔥</b>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
