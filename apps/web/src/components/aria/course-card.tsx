'use client';

import type { ReactNode } from 'react';

import { cn } from '@/lib/utils';

export interface CourseCardProps {
  name: string;
  meta: string;
  /** Progress 0–100, or `null` when the user has no progress yet (renders "—"). */
  pct: number | null;
  /** Any valid CSS color/gradient string for the card header. */
  color: string;
  /** Glyph / emoji / Icon node rendered top-right. */
  icon: ReactNode;
  active?: boolean;
  onClick?: () => void;
  /** Optional pill label shown at bottom-left of the header. */
  tag?: string;
  /**
   * Optional generated cover image (task 5.2). When set it fills the
   * header band instead of the flat `color` gradient.
   */
  cover?: string | null;
}

/**
 * Course card — header band with progress bar and meta.
 *
 * Ported from the prototype's `CourseCard`. The header's color background
 * is intentionally controlled via inline style so callers can pass any
 * gradient or token without registering a Tailwind utility.
 */
export function CourseCard({
  name,
  meta,
  pct,
  color,
  icon,
  active = false,
  onClick,
  tag = 'AP Course',
  cover = null,
}: CourseCardProps) {
  const hasPct = typeof pct === 'number';
  const clampedPct = hasPct ? Math.max(0, Math.min(100, pct!)) : 0;

  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'flex w-full flex-col overflow-hidden rounded-[18px] border-2 bg-white text-left shadow-sm transition-all duration-[250ms] ease-out',
        'hover:-translate-y-[3px] hover:shadow-lg',
        active ? 'border-indigo' : 'border-transparent',
      )}
    >
      <div
        className="relative flex h-[100px] items-end bg-cover bg-center p-4"
        style={
          cover
            ? { backgroundImage: `url(${cover})` }
            : { background: color }
        }
      >
        <div className="absolute right-3.5 top-3.5 grid h-[42px] w-[42px] place-items-center rounded-xl border border-white/20 bg-white/[0.18] text-[22px] backdrop-blur-md">
          {icon}
        </div>
        <div className="rounded-md bg-black/25 px-2.5 py-[3px] text-[10px] font-bold uppercase tracking-[0.1em] text-white backdrop-blur-sm">
          {tag}
        </div>
      </div>

      <div className="flex flex-1 flex-col p-4">
        <div className="mb-1 font-display text-[18px] font-bold tracking-[-0.015em]">{name}</div>
        <div className="mb-3.5 text-xs text-ink-3">{meta}</div>

        <div className="mt-auto flex items-center gap-2.5">
          <div className="h-[5px] flex-1 overflow-hidden rounded-[3px] bg-paper-2">
            <div
              className="h-full rounded-[3px] bg-indigo transition-[width] duration-[400ms]"
              style={{ width: `${clampedPct}%` }}
            />
          </div>
          <div className="text-[11px] font-bold tabular-nums text-ink-2">
            {hasPct ? `${clampedPct}%` : '—'}
          </div>
        </div>
      </div>
    </button>
  );
}
