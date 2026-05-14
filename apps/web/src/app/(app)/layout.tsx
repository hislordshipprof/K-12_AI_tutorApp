import type { ReactNode } from 'react';

import { AppChrome } from '@/components/dashboard/app-chrome';

/**
 * Shared layout for every in-app screen (dashboard, planner, notes, history).
 *
 * Renders the `TopNav` + left `Rail` chrome and lets each route control its
 * own body. The chrome is a client component so it can read `usePathname()`
 * for the active rail item and breadcrumb.
 */
export default function AppLayout({ children }: { children: ReactNode }) {
  return <AppChrome>{children}</AppChrome>;
}
