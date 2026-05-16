'use client';

import type { ReactNode } from 'react';

import { Icon } from '@/components/aria/icon';
import { cn } from '@/lib/utils';

export interface TopNavCrumb {
  section: string;
  page: string;
}

export interface TopNavProps {
  /** Switch to the dark chalkboard variant used in classroom screens. */
  dark?: boolean;
  /** Optional breadcrumb shown next to the logo. */
  crumb?: TopNavCrumb | null;
  onLogo?: () => void;
  /** Daily learning streak in days; hidden when zero. */
  streak?: number;
  /** Two-initial label for the avatar bubble (also used as alt text seed). */
  name?: string;
  onAvatar?: () => void;
  /** Extra content slotted before the streak/avatar pair. */
  right?: ReactNode;
  /**
   * Hide the built-in avatar button. Use when the caller renders its own
   * account control (e.g. the dropdown `AccountMenu`) via `right`.
   */
  hideAvatar?: boolean;
}

/**
 * Top app navigation — logo, optional breadcrumb, streak pill, avatar.
 *
 * Ported from the prototype's `TopNav`. Tailwind classes mirror the
 * `.top-nav` rules in styles.css.
 */
export function TopNav({
  dark = false,
  crumb = null,
  onLogo,
  streak = 5,
  name = 'Alex',
  onAvatar,
  right,
  hideAvatar = false,
}: TopNavProps) {
  return (
    <nav
      className={cn(
        'top-nav relative z-30 flex h-16 flex-shrink-0 items-center justify-between px-7 backdrop-blur-md backdrop-saturate-150',
        dark
          ? 'border-b border-white/[0.06] bg-board/95'
          : 'border-b border-border bg-paper/85',
      )}
    >
      <button
        type="button"
        onClick={onLogo}
        className="flex items-center gap-2.5 outline-none"
        aria-label="EduMind home"
      >
        <div className="logo-mark">E</div>
        <div
          className={cn(
            'font-display text-[19px] font-bold tracking-tight',
            dark ? 'text-white' : 'text-ink',
          )}
        >
          edu
          <em
            className={cn(
              'not-italic',
              dark ? 'text-amber' : 'text-indigo',
            )}
          >
            mind
          </em>
        </div>
      </button>

      {crumb && (
        <div
          className={cn(
            'flex items-center gap-2 text-[13px] font-medium',
            dark ? 'text-white/50' : 'text-ink-3',
          )}
        >
          <span>{crumb.section}</span>
          <Icon name="chev" size={14} className="opacity-40" />
          <b className={cn('font-semibold', dark ? 'text-white' : 'text-ink')}>
            {crumb.page}
          </b>
        </div>
      )}

      <div className="flex items-center gap-3.5">
        {right}
        {streak > 0 && (
          <div
            className={cn(
              'flex items-center gap-1.5 rounded-full px-3 py-1.5 text-[13px] font-semibold',
              dark
                ? 'bg-amber/[0.12] text-amber'
                : 'bg-amber-soft text-[#8A6800]',
            )}
          >
            <span className="text-sm leading-none [filter:saturate(1.3)]">🔥</span>
            <span>{streak} day</span>
          </div>
        )}
        {!hideAvatar && (
          <button
            type="button"
            onClick={onAvatar}
            className={cn(
              'grid h-9 w-9 cursor-pointer place-items-center rounded-full border-2 text-[13px] font-bold text-white shadow-md',
              'bg-gradient-to-br from-coral to-amber',
              dark ? 'border-board' : 'border-white',
            )}
            aria-label={`${name} — account menu`}
          >
            {name.slice(0, 2).toUpperCase()}
          </button>
        )}
      </div>
    </nav>
  );
}
