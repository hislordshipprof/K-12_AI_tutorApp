'use client';

import { Icon } from '@/components/aria/icon';
import { HistoryRow, type HistoryRowData } from '@/components/dashboard/history-row';

const ROWS: HistoryRowData[] = [
  {
    t: 'Wave Properties & Anatomy',
    s: 'AP Physics 1 · Unit 4 · 18 min',
    d: 'Today',
    score: 92,
    status: 'In progress',
  },
  {
    t: 'Introduction to Waves',
    s: 'AP Physics 1 · Unit 4 · 12 min',
    d: 'Yesterday',
    score: 95,
  },
  {
    t: 'Momentum & Collisions',
    s: 'AP Physics 1 · Unit 3 · 20 min',
    d: 'May 11',
    score: 88,
  },
  {
    t: 'Work-Energy Theorem',
    s: 'AP Physics 1 · Unit 3 · 16 min',
    d: 'May 10',
    score: 76,
  },
  {
    t: 'Friction & Normal Force',
    s: 'AP Physics 1 · Unit 2 · 14 min',
    d: 'May 9',
    score: 91,
  },
  {
    t: "Newton's Third Law",
    s: 'AP Physics 1 · Unit 2 · 12 min',
    d: 'May 8',
    score: 64,
  },
  {
    t: 'F=ma — Net Forces',
    s: 'AP Physics 1 · Unit 2 · 18 min',
    d: 'May 6',
    score: 89,
  },
  {
    t: 'Projectile Motion',
    s: 'AP Physics 1 · Unit 1 · 22 min',
    d: 'May 5',
    score: 84,
  },
  {
    t: 'Motion Graphs',
    s: 'AP Physics 1 · Unit 1 · 15 min',
    d: 'May 3',
    score: 96,
  },
];

export default function HistoryPage() {
  return (
    <div className="mx-auto max-w-[1180px] px-8 pb-20 pt-8">
      <div className="mb-[18px] flex items-center justify-between">
        <div>
          <div className="font-display text-4xl font-bold tracking-[-0.03em]">
            Lesson history
          </div>
          <div className="mt-1 text-sm text-ink-3">
            Every lesson, with full replay and your Q&amp;A. 9 lessons over the
            past 11 days.
          </div>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            className="inline-flex items-center gap-1.5 rounded-[10px] border-[1.5px] border-border-2 bg-transparent px-3.5 py-2 text-[13px] font-semibold text-ink transition-colors hover:bg-black/5"
          >
            <Icon name="search" size={14} /> Find
          </button>
          <button
            type="button"
            className="inline-flex items-center gap-1.5 rounded-[10px] border-[1.5px] border-border-2 bg-transparent px-3.5 py-2 text-[13px] font-semibold text-ink transition-colors hover:bg-black/5"
          >
            <Icon name="download" size={14} /> Export
          </button>
        </div>
      </div>
      {ROWS.map((r, i) => (
        <HistoryRow key={i} row={r} />
      ))}
    </div>
  );
}
