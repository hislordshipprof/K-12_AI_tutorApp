import { redirect } from 'next/navigation';
import type { ReactNode } from 'react';

import { TeachChrome } from '@/components/teach/teach-chrome';
import { getSupabaseServerClient } from '@/lib/supabase/server';

/**
 * Layout for the teacher admin board (`/teach/*`) — task 3.1 role gate.
 *
 * Two layers protect the board:
 *  - middleware redirects an unauthenticated visitor of any `/teach` path
 *    to `/login` (see `src/middleware.ts` PROTECTED_PREFIXES);
 *  - this layout additionally reads the signed-in user's `profiles.role`
 *    and sends a non-teacher (a student) to `/dashboard`.
 *
 * So only a `teacher` or `admin` profile reaches a `/teach` screen.
 */
export default async function TeachLayout({
  children,
}: {
  children: ReactNode;
}) {
  let authed = false;
  let role = 'student';

  try {
    const supabase = await getSupabaseServerClient();
    const {
      data: { user },
    } = await supabase.auth.getUser();
    if (user) {
      authed = true;
      const { data: profile } = await supabase
        .from('profiles')
        .select('role')
        .eq('id', user.id)
        .single();
      role = (profile?.role as string | undefined) ?? 'student';
    }
  } catch {
    // Supabase env not configured — fail closed (treat as unauthenticated).
  }

  if (!authed) redirect('/login');
  if (role !== 'teacher' && role !== 'admin') redirect('/dashboard');

  return <TeachChrome>{children}</TeachChrome>;
}
