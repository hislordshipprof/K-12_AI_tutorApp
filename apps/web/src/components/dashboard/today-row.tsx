import { cn } from '@/lib/utils';

export type TodayDot = 'default' | 'done' | 'coral' | 'amber';

export interface TodayRowProps {
  time: string;
  title: string;
  meta: string;
  dot?: TodayDot;
  tag: string;
  tagClass: string;
}

const DOT_CLASSES: Record<TodayDot, string> = {
  default: 'bg-indigo',
  done: 'bg-mint',
  coral: 'bg-coral',
  amber: 'bg-amber',
};

/**
 * One row of the "Today" agenda widget — time, status dot, title/meta, tag.
 *
 * Ported from `.today-row` in the prototype.
 */
export function TodayRow({
  time,
  title,
  meta,
  dot = 'default',
  tag,
  tagClass,
}: TodayRowProps) {
  return (
    <div className="flex items-center gap-3.5 border-b border-dashed border-border py-2.5 last:border-b-0">
      <div className="w-16 font-mono text-xs font-medium text-ink-3">{time}</div>
      <div className={cn('h-2 w-2 rounded-full', DOT_CLASSES[dot])} />
      <div className="flex-1">
        <div className="text-[13.5px] font-semibold text-ink">{title}</div>
        <div className="mt-px text-[11px] text-ink-3">{meta}</div>
      </div>
      <div
        className={cn(
          'rounded-md px-2 py-[3px] text-[10px] font-bold uppercase tracking-[0.05em]',
          tagClass,
        )}
      >
        {tag}
      </div>
    </div>
  );
}
