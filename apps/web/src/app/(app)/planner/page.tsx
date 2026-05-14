'use client';

import { WeekDayColumn, type WeekDay } from '@/components/dashboard/week-day-column';

const DAYS: WeekDay[] = [
  {
    d: 'Mon',
    n: 12,
    blocks: [
      { c: 'mint done', t: 'Wave Intro', m: '✓ 12m' },
      { c: 'mint done', t: 'Crests + Troughs', m: '✓ 14m' },
    ],
  },
  {
    d: 'Tue',
    n: 13,
    today: true,
    blocks: [
      { c: 'indigo', t: 'Wave Properties', m: '18m · lesson' },
      { c: 'amber', t: 'Equation drill', m: '15m · quiz' },
      { c: 'coral', t: 'Office hours', m: '30m · Aria' },
      { c: 'amber', t: 'Flashcards', m: '8m' },
    ],
  },
  {
    d: 'Wed',
    n: 14,
    blocks: [
      { c: 'indigo', t: 'Wave Speed', m: '14m · lesson' },
      { c: 'lav', t: 'FRQ workshop', m: '25m' },
    ],
  },
  {
    d: 'Thu',
    n: 15,
    blocks: [
      { c: 'indigo', t: 'Superposition', m: '20m · lesson' },
      { c: 'amber', t: 'Practice set', m: '8 problems' },
    ],
  },
  {
    d: 'Fri',
    n: 16,
    blocks: [{ c: 'indigo', t: 'Standing Waves', m: '16m · lesson' }],
  },
  {
    d: 'Sat',
    n: 17,
    blocks: [{ c: 'lav', t: 'Unit 4 mock', m: '45m · exam' }],
  },
  {
    d: 'Sun',
    n: 18,
    blocks: [{ c: 'mint', t: 'Light day ✨', m: 'rest' }],
  },
];

export default function PlannerPage() {
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
          <div className="grid grid-cols-7 gap-2">
            {DAYS.map((day) => (
              <WeekDayColumn key={day.d} day={day} />
            ))}
          </div>
        </div>

        {/* SIDEBAR */}
        <div className="flex flex-col gap-3.5">
          <div className="rounded-[18px] border border-border bg-white p-5 shadow-sm">
            <div className="mb-3 font-display text-base font-bold tracking-[-0.015em]">
              This week&apos;s goal
            </div>
            <GoalRow done text="Finish Wave Intro" />
            <GoalRow text="Master amplitude + wavelength" />
            <GoalRow text="Score 85%+ on Unit 4 mock" />
            <GoalRow text="Build 22-card wave deck" />
          </div>

          <div className="rounded-[18px] border border-indigo bg-indigo p-5 text-white shadow-sm">
            <div className="mb-3 font-display text-base font-bold tracking-[-0.015em] text-white">
              Aria&apos;s note
            </div>
            <p className="font-display text-[13px] italic leading-[1.55] opacity-[0.92]">
              You&apos;re{' '}
              <b className="not-italic text-amber">2 days ahead</b> of pace for
              an AP 5 — nice. I lightened Sunday so you can rest. Push hard
              Saturday on the mock and we&apos;re golden.
            </p>
            <button
              type="button"
              className="mt-3 rounded-[10px] bg-amber px-3.5 py-2 text-[13px] font-semibold text-[#5C3A00] transition-all hover:-translate-y-px"
            >
              Adjust plan
            </button>
          </div>

          <div className="rounded-[18px] border border-border bg-white p-5 shadow-sm">
            <div className="mb-3 font-display text-base font-bold tracking-[-0.015em]">
              Weekly stats
            </div>
            <div className="mb-2 flex justify-between text-[13px]">
              <span className="text-ink-3">Study time</span>
              <b>4h 12m / 6h</b>
            </div>
            <div className="mb-3.5 h-1.5 rounded-[3px] bg-paper-2">
              <div className="h-full w-[70%] rounded-[3px] bg-indigo" />
            </div>
            <div className="mb-2 flex justify-between text-[13px]">
              <span className="text-ink-3">Quiz accuracy</span>
              <b className="text-mint">87% ↑3</b>
            </div>
            <div className="flex justify-between text-[13px]">
              <span className="text-ink-3">Topics mastered</span>
              <b>2 of 5</b>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function GoalRow({ text, done = false }: { text: string; done?: boolean }) {
  return (
    <div className="mb-2 flex items-center gap-2.5 rounded-[10px] bg-paper p-2.5">
      <div
        className={
          done
            ? 'relative h-[18px] w-[18px] flex-shrink-0 rounded-full border-2 border-mint bg-mint'
            : 'relative h-[18px] w-[18px] flex-shrink-0 rounded-full border-2 border-border-2'
        }
      >
        {done && (
          <span className="absolute left-1 top-[1px] h-2 w-1 rotate-45 border-b-2 border-r-2 border-white" />
        )}
      </div>
      <div
        className={
          done
            ? 'flex-1 text-[13px] font-medium text-ink-3 line-through'
            : 'flex-1 text-[13px] font-medium'
        }
      >
        {text}
      </div>
    </div>
  );
}
