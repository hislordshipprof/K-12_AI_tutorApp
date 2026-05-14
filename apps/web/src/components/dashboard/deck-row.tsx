import { Icon } from '@/components/aria/icon';
import { cn } from '@/lib/utils';

export interface DeckRowProps {
  title: string;
  count: number;
  due: number;
  mastery: number;
}

function masteryColor(m: number): string {
  if (m > 85) return 'text-mint';
  if (m > 70) return 'text-amber';
  return 'text-coral';
}

/**
 * One flashcard-deck row used in the Notebook → Flashcards tab.
 *
 * Ported from `.deck` in the prototype.
 */
export function DeckRow({ title, count, due, mastery }: DeckRowProps) {
  return (
    <div className="flex cursor-pointer items-center gap-3.5 rounded-[18px] border border-border bg-white p-[18px] transition-all duration-[250ms] hover:-translate-y-0.5 hover:shadow-md">
      <div className="relative grid h-14 w-14 flex-shrink-0 place-items-center rounded-[14px] bg-gradient-to-br from-indigo to-lavender text-white shadow-sm">
        <Icon name="book" size={22} />
      </div>
      <div className="flex-1">
        <div className="font-display text-base font-bold tracking-[-0.01em]">
          {title}
        </div>
        <div className="mt-[3px] flex gap-3 text-xs text-ink-3">
          <span>
            <b className="font-semibold text-ink-2">{count}</b> cards
          </span>
          <span className={due ? 'text-coral' : 'text-ink-3'}>
            <b className="font-semibold">{due}</b> due today
          </span>
        </div>
      </div>
      <div className="w-[60px] text-right">
        <div
          className={cn(
            'font-display text-[20px] font-bold',
            masteryColor(mastery),
          )}
        >
          {mastery}%
        </div>
        <div className="text-[9px] uppercase tracking-[0.08em] text-ink-3">
          Mastery
        </div>
      </div>
    </div>
  );
}
