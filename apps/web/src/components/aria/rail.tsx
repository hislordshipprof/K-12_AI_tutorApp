'use client';

import { Icon, type IconName } from '@/components/aria/icon';
import { cn } from '@/lib/utils';

export type RailScreen =
  | 'landing'
  | 'dashboard'
  | 'planner'
  | 'notes'
  | 'history'
  | 'classroom'
  | 'settings';

interface RailItem {
  id: RailScreen;
  icon: IconName;
  label: string;
}

const ITEMS: RailItem[] = [
  { id: 'dashboard', icon: 'home', label: 'Home' },
  { id: 'planner', icon: 'planner', label: 'Plan' },
  { id: 'notes', icon: 'notes', label: 'Notes' },
  { id: 'history', icon: 'history', label: 'History' },
];

export interface RailProps {
  current: RailScreen;
  onNav: (screen: RailScreen) => void;
}

interface RailButtonProps {
  active?: boolean;
  label: string;
  onClick?: () => void;
  iconName: IconName;
}

function RailButton({ active, label, onClick, iconName }: RailButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      className={cn(
        'group relative grid h-11 w-11 cursor-pointer place-items-center rounded-xl transition-all duration-200',
        active
          ? 'bg-ink text-white'
          : 'text-ink-3 hover:bg-paper-2 hover:text-ink',
      )}
    >
      <Icon name={iconName} size={22} />
      <span
        className={cn(
          'pointer-events-none absolute left-[54px] top-1/2 z-50 -translate-y-1/2 -translate-x-1 whitespace-nowrap rounded-md bg-ink px-2.5 py-1.5 text-xs font-semibold text-white opacity-0 transition-all duration-150',
          'group-hover:translate-x-0 group-hover:opacity-100',
        )}
      >
        {label}
      </span>
    </button>
  );
}

/**
 * Left rail — primary in-app navigation (72px-wide column).
 *
 * Ported from the prototype's `Rail`. The icons-only width and hover
 * tooltips match the `.rail` rules in styles.css.
 */
export function Rail({ current, onNav }: RailProps) {
  return (
    <aside className="flex flex-col items-center gap-1.5 border-r border-border bg-white py-[18px]">
      <button
        type="button"
        onClick={() => onNav('landing')}
        className="logo-mark mb-3.5"
        aria-label="EduMind landing"
      >
        E
      </button>
      {ITEMS.map((it) => (
        <RailButton
          key={it.id}
          iconName={it.icon}
          label={it.label}
          active={current === it.id}
          onClick={() => onNav(it.id)}
        />
      ))}
      <div className="my-2 h-px w-[30px] bg-border" />
      <RailButton iconName="play" label="Resume lesson" onClick={() => onNav('classroom')} />
      <div className="mt-auto">
        <RailButton iconName="settings" label="Settings" onClick={() => onNav('settings')} />
      </div>
    </aside>
  );
}
