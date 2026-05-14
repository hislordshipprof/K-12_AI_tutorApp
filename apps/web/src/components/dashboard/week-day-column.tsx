import { cn } from '@/lib/utils';

export type WeekBlockColor =
  | 'mint'
  | 'mint done'
  | 'indigo'
  | 'amber'
  | 'coral'
  | 'lav';

export interface WeekBlock {
  c: WeekBlockColor;
  t: string;
  m: string;
}

export interface WeekDay {
  d: string;
  n: number;
  today?: boolean;
  blocks: WeekBlock[];
}

export interface WeekDayColumnProps {
  day: WeekDay;
}

const BLOCK_BASE = 'rounded-[10px] border-l-[3px] p-2.5 text-[11.5px] cursor-pointer';

const BLOCK_COLORS: Record<string, string> = {
  indigo: 'border-l-indigo bg-indigo-soft text-indigo-deep',
  mint: 'border-l-mint bg-mint-soft text-[#1C7A47]',
  amber: 'border-l-amber bg-amber-soft text-[#8A6800]',
  coral: 'border-l-coral bg-coral-soft text-[#A1452B]',
  lav: 'border-l-lavender bg-lavender-soft text-[#5B2EAA]',
};

/**
 * One day column in the weekly planner grid.
 *
 * Ported from `.week-col` / `.week-block`.
 */
export function WeekDayColumn({ day }: WeekDayColumnProps) {
  return (
    <div
      className={cn(
        'flex min-h-[380px] min-w-0 flex-col gap-2 rounded-2xl border bg-white p-3 pb-[18px]',
        day.today
          ? 'border-indigo shadow-[0_0_0_4px_rgba(91,91,229,0.1)]'
          : 'border-border',
      )}
    >
      <div className="text-[10px] font-bold uppercase tracking-[0.1em] text-ink-3">
        {day.d}
      </div>
      <div
        className={cn(
          'mb-2 font-display text-[22px] font-bold leading-none tracking-[-0.02em]',
          day.today && 'text-indigo',
        )}
      >
        {day.n}
      </div>
      {day.blocks.map((b, j) => {
        const tokens = b.c.split(' ');
        const colorKey = tokens[0] ?? 'indigo';
        const isDone = tokens.includes('done');
        return (
          <div
            key={j}
            className={cn(
              BLOCK_BASE,
              BLOCK_COLORS[colorKey],
              isDone && 'opacity-50',
            )}
          >
            <div
              className={cn(
                'mb-0.5 break-words font-semibold text-ink',
                isDone && 'line-through',
              )}
            >
              {b.t}
            </div>
            <div className="font-mono text-[10px] text-ink-3">{b.m}</div>
          </div>
        );
      })}
    </div>
  );
}
