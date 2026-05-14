'use client';

import { useQuery } from '@tanstack/react-query';

import { Icon } from '@/components/aria/icon';
import { HistoryRow, type HistoryRowData } from '@/components/dashboard/history-row';
import { api } from '@/lib/api';

interface HistoryRowApi {
  id: string;
  topic_id: string | null;
  topic_name: string | null;
  started_at: string;
  ended_at: string | null;
  duration_min: number | null;
  score_pct: number | null;
}

function relDate(iso: string): string {
  const then = new Date(iso);
  const now = new Date();
  const dayMs = 24 * 60 * 60 * 1000;
  const diff = Math.floor((now.getTime() - then.getTime()) / dayMs);
  if (diff <= 0) return 'Today';
  if (diff === 1) return 'Yesterday';
  if (diff < 7) return `${diff}d ago`;
  return then.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

function toRow(api: HistoryRowApi): HistoryRowData {
  const meta = [
    'AP Physics 1',
    api.duration_min ? `${api.duration_min} min` : null,
  ]
    .filter(Boolean)
    .join(' · ');
  return {
    t: api.topic_name ?? 'Lesson',
    s: meta,
    d: relDate(api.started_at),
    score: api.score_pct ?? undefined,
    status: api.ended_at ? undefined : 'In progress',
  };
}

export default function HistoryPage() {
  const { data: rows = [], isLoading } = useQuery<HistoryRowData[]>({
    queryKey: ['history'],
    queryFn: async () => {
      try {
        const data = await api<HistoryRowApi[]>('/v1/history');
        return data.map(toRow);
      } catch {
        return [];
      }
    },
    staleTime: 30_000,
  });

  return (
    <div className="mx-auto max-w-[1180px] px-8 pb-20 pt-8">
      <div className="mb-[18px] flex items-center justify-between">
        <div>
          <div className="font-display text-4xl font-bold tracking-[-0.03em]">
            Lesson history
          </div>
          <div className="mt-1 text-sm text-ink-3">
            {rows.length > 0
              ? `${rows.length} lesson${rows.length === 1 ? '' : 's'}, newest first.`
              : 'Every lesson you finish lands here with replay + Q&A.'}
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
      {rows.length === 0 && !isLoading && (
        <div className="rounded-2xl border border-dashed border-border bg-white px-6 py-14 text-center">
          <div className="text-base font-semibold text-ink">No history yet</div>
          <div className="mt-1 text-sm text-ink-3">
            Finish your first lesson and it’ll show up here.
          </div>
        </div>
      )}
      {rows.map((r, i) => (
        <HistoryRow key={i} row={r} />
      ))}
    </div>
  );
}
