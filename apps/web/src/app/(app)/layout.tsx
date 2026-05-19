import type { ReactNode } from 'react';

import { AppChrome } from '@/components/dashboard/app-chrome';
import { getSupabaseServerClient } from '@/lib/supabase/server';

/**
 * Shared layout for every in-app screen (dashboard, planner, notes, history).
 *
 * Renders the `TopNav` + left `Rail` chrome and lets each route control its
 * own body. The chrome is a client component so it can read `usePathname()`
 * for the active rail item and breadcrumb.
 *
 * The signed-in user's `profiles.role` is read here, server-side (the same
 * pattern as `/teach/layout.tsx`), and passed to the chrome — so a
 * teacher/admin gets a "Teacher board" rail entry and a student never does.
 */
export default async function AppLayout({ children }: { children: ReactNode }) {
  let role = 'student';
  try {
    const supabase = await getSupabaseServerClient();
    const {
      data: { user },
    } = await supabase.auth.getUser();
    if (user) {
      const { data: profile } = await supabase
        .from('profiles')
        .select('role')
        .eq('id', user.id)
        .single();
      role = (profile?.role as string | undefined) ?? 'student';
    }
  } catch {
    // Supabase env not configured — treat as a student (least privilege).
  }

  return <AppChrome role={role}>{children}</AppChrome>;
}
