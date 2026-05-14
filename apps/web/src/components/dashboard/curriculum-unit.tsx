'use client';

import { useRouter } from 'next/navigation';

import { Icon } from '@/components/aria/icon';
import { cn } from '@/lib/utils';

export interface Topic {
  name: string;
  dur: string;
  state?: 'done' | 'current';
}

export interface Unit {
  id: string;
  n: number;
  name: string;
  count: number;
  done: number;
  status?: 'done';
  topics?: Topic[];
}

export interface CurriculumUnitProps {
  unit: Unit;
  open: boolean;
  onToggle: () => void;
}

/**
 * One collapsible curriculum unit row + its (optional) topic list.
 *
 * Ported from the prototype's `.unit` / `.topic` blocks.
 */
export function CurriculumUnit({ unit, open, onToggle }: CurriculumUnitProps) {
  const router = useRouter();
  const pct = unit.count > 0 ? (unit.done / unit.count) * 100 : 0;

  return (
    <div
      className={cn(
        'border-b border-border last:border-b-0',
        open && 'open',
        unit.status === 'done' && 'done',
      )}
    >
      <button
        type="button"
        onClick={onToggle}
        className="group flex w-full items-center gap-3.5 px-[22px] py-3.5 transition-colors hover:bg-paper"
      >
        <span
          className={cn(
            'grid h-[30px] w-[30px] flex-shrink-0 place-items-center rounded-[9px] font-mono text-xs font-bold transition-all duration-200',
            unit.status === 'done'
              ? 'bg-mint text-white'
              : open
                ? 'bg-ink text-white'
                : 'bg-paper-2 text-ink-2',
          )}
        >
          {unit.n}
        </span>
        <span className="flex-1 text-left text-[15px] font-semibold tracking-[-0.005em]">
          {unit.name}
        </span>
        <span className="text-xs text-ink-3">
          {unit.done}/{unit.count} done
        </span>
        <span className="mr-2 h-1 w-[100px] overflow-hidden rounded-[2px] bg-paper-2">
          <span
            className="block h-full rounded-[2px] bg-indigo"
            style={{ width: `${pct}%` }}
          />
        </span>
        <span
          className={cn(
            'grid h-6 w-6 place-items-center text-ink-3 transition-transform duration-200',
            open && 'rotate-90',
          )}
        >
          <Icon name="chev" size={16} />
        </span>
      </button>
      {open && unit.topics && (
        <div className="px-[22px] pb-3.5 pl-[66px] pt-1">
          {unit.topics.map((t, i) => (
            <TopicRow
              key={i}
              topic={t}
              onClick={() => {
                if (t.state === 'current') {
                  router.push('/classroom/wave-properties-anatomy');
                }
              }}
              onAction={(e) => {
                e.stopPropagation();
                router.push('/classroom/wave-properties-anatomy');
              }}
            />
          ))}
        </div>
      )}
    </div>
  );
}

interface TopicRowProps {
  topic: Topic;
  onClick: () => void;
  onAction: (e: React.MouseEvent) => void;
}

function TopicRow({ topic, onClick, onAction }: TopicRowProps) {
  const isCurrent = topic.state === 'current';
  const isDone = topic.state === 'done';
  return (
    <div
      onClick={onClick}
      className={cn(
        'group mb-0.5 flex cursor-pointer items-center gap-3 rounded-[10px] px-3 py-2 transition-colors',
        isCurrent ? 'bg-indigo-soft' : 'hover:bg-paper',
      )}
    >
      <span
        className={cn(
          'relative h-[18px] w-[18px] flex-shrink-0 rounded-full border-2',
          isDone && 'border-mint bg-mint',
          isCurrent && 'border-indigo bg-indigo shadow-[0_0_0_4px_rgba(91,91,229,0.18)]',
          !isDone && !isCurrent && 'border-border-2 bg-white',
        )}
      >
        {isDone && (
          <span className="absolute left-[5px] top-[2px] h-2 w-1 rotate-45 border-b-2 border-r-2 border-white" />
        )}
        {isCurrent && (
          <span className="absolute left-1/2 top-1/2 h-1.5 w-1.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-white" />
        )}
      </span>
      <span
        className={cn(
          'flex-1 text-[13.5px]',
          isCurrent ? 'font-semibold' : 'font-medium',
        )}
      >
        {topic.name}
      </span>
      <span className="text-[11px] tabular-nums text-ink-3">{topic.dur}</span>
      <button
        type="button"
        onClick={onAction}
        className={cn(
          'rounded-lg px-3 py-1.5 text-xs font-semibold text-white transition-opacity duration-150',
          isCurrent ? 'bg-indigo opacity-100' : 'bg-ink opacity-0 group-hover:opacity-100',
        )}
      >
        {isDone ? 'Replay' : isCurrent ? 'Continue →' : 'Start'}
      </button>
    </div>
  );
}
