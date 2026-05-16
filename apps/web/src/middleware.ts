import { NextResponse, type NextRequest } from 'next/server';

import { updateSupabaseSession } from '@/lib/supabase/middleware';

/**
 * Paths that require an authenticated user. Anything that starts with one
 * of these prefixes will be redirected to `/login` when there is no
 * session. The classroom prefix uses `startsWith` matching so dynamic
 * routes like `/classroom/<slug>` are gated too.
 */
const PROTECTED_PREFIXES = [
  '/dashboard',
  '/planner',
  '/notes',
  '/history',
  '/classroom',
  '/redeem-invite',
  '/teach',
] as const;

function isProtectedPath(pathname: string): boolean {
  return PROTECTED_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
  );
}

export async function middleware(request: NextRequest) {
  const { response, user } = await updateSupabaseSession(request);

  if (!user && isProtectedPath(request.nextUrl.pathname)) {
    const redirectUrl = request.nextUrl.clone();
    redirectUrl.pathname = '/login';
    redirectUrl.searchParams.set('redirectTo', request.nextUrl.pathname);
    return NextResponse.redirect(redirectUrl);
  }

  return response;
}

export const config = {
  // Run middleware on every route except Next.js internals and static
  // assets. Auth cookie refresh needs to happen for navigation requests,
  // not for `/_next/*` chunks or favicons.
  matcher: ['/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)$).*)'],
};
