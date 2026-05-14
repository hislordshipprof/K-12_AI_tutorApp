'use client';

import { usePathname, useRouter } from 'next/navigation';
import { useMemo, type ReactNode } from 'react';

import { Rail, type RailScreen } from '@/components/aria/rail';
import { TopNav, type TopNavCrumb } from '@/components/aria/top-nav';
import { useMe } from '@/hooks/use-me';

const ROUTE_TO_SCREEN: Record<string, RailScreen> = {
  '/dashboard': 'dashboard',
  '/planner': 'planner',
  '/notes': 'notes',
  '/history': 'history',
};

const SCREEN_TO_ROUTE: Record<RailScreen, string> = {
  landing: '/',
  dashboard: '/dashboard',
  planner: '/planner',
  notes: '/notes',
  history: '/history',
  classroom: '/classroom/wave-properties-anatomy',
  settings: '/settings',
};

const CRUMBS: Record<string, TopNavCrumb> = {
  '/dashboard': { section: 'Home', page: 'Dashboard' },
  '/planner': { section: 'Plan', page: 'This week' },
  '/notes': { section: 'Notes', page: 'Notebook' },
  '/history': { section: 'History', page: 'Lessons' },
};

/**
 * Client-side chrome wrapping every in-app screen.
 *
 * Owns the route-derived breadcrumb + active rail state so the server
 * layout can stay declarative and content-focused.
 */
export function AppChrome({ children }: { children: ReactNode }) {
  const pathname = usePathname() ?? '/dashboard';
  const router = useRouter();
  const { data: me } = useMe();

  const { current, crumb } = useMemo(() => {
    const key = Object.keys(ROUTE_TO_SCREEN).find((p) => pathname.startsWith(p));
    return {
      current: (key ? ROUTE_TO_SCREEN[key] : 'dashboard') as RailScreen,
      crumb: key ? CRUMBS[key] : CRUMBS['/dashboard'],
    };
  }, [pathname]);

  return (
    <div className="flex h-screen flex-col bg-paper">
      <TopNav
        crumb={crumb ?? null}
        streak={me?.streak_days ?? 0}
        name={me?.full_name ?? 'Guest'}
        onLogo={() => router.push('/')}
      />
      <div className="flex min-h-0 flex-1">
        <Rail
          current={current}
          onNav={(screen) => router.push(SCREEN_TO_ROUTE[screen])}
        />
        <main className="min-w-0 flex-1 overflow-auto">{children}</main>
      </div>
    </div>
  );
}
