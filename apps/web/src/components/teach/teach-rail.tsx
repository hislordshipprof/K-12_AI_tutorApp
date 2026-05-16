'use client';

import { usePathname, useRouter } from 'next/navigation';

import { Icon, type IconName } from '@/components/aria/icon';
import { cn } from '@/lib/utils';

interface TeachRailItem {
  id: 'home' | 'classes' | 'courses';
  icon: IconName;
  label: string;
}

const ITEMS: TeachRailItem[] = [
  { id: 'home', icon: 'home', label: 'Home' },
  { id: 'classes', icon: 'users', label: 'Classes' },
  { id: 'courses', icon: 'course', label: 'Courses' },
];

interface RailButtonProps {
  active?: boolean;
  label: string;
  iconName: IconName;
  onClick?: () => void;
}

function RailButton({ active, label, iconName, onClick }: RailButtonProps) {
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
 * Left rail for the teacher admin board (`/teach`).
 *
 * Mirrors the student `Rail` chrome (72px icon column, hover tooltips) but
 * with teacher-scoped destinations. `/teach` is itself the classes + courses
 * overview, so the Classes / Courses items smooth-scroll to that page's
 * sections rather than routing to separate index pages.
 */
export function TeachRail() {
  const router = useRouter();
  const pathname = usePathname() ?? '/teach';

  const go = (id: TeachRailItem['id']) => {
    if (id === 'home') {
      router.push('/teach');
      return;
    }
    const el =
      typeof document !== 'undefined' ? document.getElementById(id) : null;
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    } else {
      router.push('/teach');
    }
  };

  return (
    <aside className="flex flex-col items-center gap-1.5 border-r border-border bg-white py-[18px]">
      <button
        type="button"
        onClick={() => router.push('/teach')}
        className="logo-mark mb-3.5"
        aria-label="Teacher home"
      >
        E
      </button>
      {ITEMS.map((it) => (
        <RailButton
          key={it.id}
          iconName={it.icon}
          label={it.label}
          active={
            (it.id === 'home' && pathname === '/teach') ||
            (it.id === 'classes' && pathname.startsWith('/teach/classes')) ||
            (it.id === 'courses' && pathname.startsWith('/teach/courses'))
          }
          onClick={() => go(it.id)}
        />
      ))}
    </aside>
  );
}
