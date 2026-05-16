'use client';

import { usePathname, useRouter } from 'next/navigation';
import { useMemo, type ReactNode } from 'react';

import { AccountMenu } from '@/components/account-menu';
import { Rail, type RailScreen } from '@/components/aria/rail';
import { TopNav, type TopNavCrumb } from '@/components/aria/top-nav';
import { useMe } from '@/hooks/use-me';
import { resolveClassroomTopicPath } from '@/lib/api';

const ROUTE_TO_SCREEN: Record<string, RailScreen> = {
  '/dashboard': 'dashboard',
  '/planner': 'planner',
  '/notes': 'notes',
  '/history': 'history',
};

// `classroom` is intentionally absent — it has no static route. The rail's
// "Resume lesson" entry resolves a real topic UUID at click time (see
// `onNav` below) so the classroom always opens on a real DB topic.
const SCREEN_TO_ROUTE: Record<Exclude<RailScreen, 'classroom'>, string> = {
  landing: '/',
  dashboard: '/dashboard',
  planner: '/planner',
  notes: '/notes',
  history: '/history',
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
        hideAvatar
        right={<AccountMenu name={me?.full_name ?? 'Guest'} />}
      />
      <div className="flex min-h-0 flex-1">
        <Rail
          current={current}
          onNav={async (screen) => {
            if (screen === 'classroom') {
              // Resume lesson — resolve a real topic UUID; fall back to the
              // dashboard (which has its own resume logic) if unreachable.
              const path = await resolveClassroomTopicPath();
              router.push(path ?? '/dashboard');
              return;
            }
            router.push(SCREEN_TO_ROUTE[screen]);
          }}
        />
        <main className="min-w-0 flex-1 overflow-auto">{children}</main>
      </div>
    </div>
  );
}
