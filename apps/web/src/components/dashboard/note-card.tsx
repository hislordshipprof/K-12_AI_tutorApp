import type { ReactNode } from 'react';

import { Icon } from '@/components/aria/icon';
import { cn } from '@/lib/utils';

export type NoteColor = '' | 'amber' | 'coral' | 'mint' | 'lav' | 'indigo';

export interface NoteCardProps {
  color: NoteColor;
  tag: string;
  title: string;
  body: ReactNode;
  date: string;
}

const COLOR_CLASSES: Record<NoteColor, string> = {
  '': 'bg-white',
  amber: 'bg-amber-soft',
  coral: 'bg-coral-soft',
  mint: 'bg-mint-soft',
  lav: 'bg-lavender-soft',
  indigo: 'bg-indigo-soft',
};

/**
 * Sticky-note style card used in the Notebook grid.
 *
 * Ported from `.note` blocks (with `.note.<color>` variants).
 */
export function NoteCard({ color, tag, title, body, date }: NoteCardProps) {
  return (
    <div
      className={cn(
        'relative flex cursor-pointer flex-col gap-2.5 overflow-hidden rounded-[18px] border border-border p-5 transition-all duration-[250ms]',
        'hover:-translate-y-[3px] hover:shadow-md',
        COLOR_CLASSES[color],
      )}
    >
      <div className="inline-block self-start rounded-md bg-white/55 px-2 py-[3px] text-[10px] font-bold uppercase tracking-[0.1em] text-ink-2">
        {tag}
      </div>
      <div className="font-display text-[18px] font-semibold leading-[1.25] tracking-[-0.015em]">
        {title}
      </div>
      <div className="flex-1 text-[13px] leading-[1.55] text-ink-2 [&_code]:rounded [&_code]:bg-black/[0.06] [&_code]:px-1.5 [&_code]:py-px [&_code]:font-mono [&_code]:text-xs">
        {body}
      </div>
      <div className="flex items-center justify-between border-t border-dashed border-black/10 pt-2 text-[11px] font-medium text-ink-3">
        <span>{date}</span>
        <span className="flex gap-2.5">
          <Icon name="book" size={13} />
          <Icon name="sparkle" size={13} />
        </span>
      </div>
    </div>
  );
}
