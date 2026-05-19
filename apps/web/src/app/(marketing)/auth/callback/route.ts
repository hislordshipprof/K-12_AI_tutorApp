import { NextResponse, type NextRequest } from 'next/server';

import { getSupabaseServerClient } from '@/lib/supabase/server';

/**
 * OAuth + magic-link redirect target.
 *
 * Supabase appends `?code=<pkce>` (and optionally `?next=<path>`) when it
 * bounces the browser back to us after the user clicks the magic link or
 * completes the Google consent screen. We swap that code for a session
 * (which sets the auth cookies via the `setAll` hook in
 * `getSupabaseServerClient`) and then forward the user to their intended
 * destination.
 *
 * Destination: an explicit, safe `next` deep link is always honoured. With
 * no `next`, we route by `profiles.role` — a `teacher`/`admin` lands on the
 * teacher board (`/teach`), everyone else on the student `/dashboard`.
 */

/** A `next` param is only honoured if it is a same-origin absolute path. */
function isSafeNext(value: string | null): value is string {
  return !!value && value.startsWith('/') && !value.startsWith('//');
}

export async function GET(request: NextRequest) {
  const { searchParams, origin } = request.nextUrl;
  const code = searchParams.get('code');
  const next = searchParams.get('next');

  if (!code) {
    const url = new URL('/login', origin);
    url.searchParams.set('error', 'missing_code');
    return NextResponse.redirect(url);
  }

  const supabase = await getSupabaseServerClient();
  const { error } = await supabase.auth.exchangeCodeForSession(code);

  if (error) {
    const url = new URL('/login', origin);
    url.searchParams.set('error', error.message);
    return NextResponse.redirect(url);
  }

  // An explicit, safe deep link wins — don't override an intentional target.
  if (isSafeNext(next)) {
    return NextResponse.redirect(new URL(next, origin));
  }

  // No deep link — route by role.
  let destination = '/dashboard';
  try {
    const {
      data: { user },
    } = await supabase.auth.getUser();
    if (user) {
      const { data: profile } = await supabase
        .from('profiles')
        .select('role')
        .eq('id', user.id)
        .single();
      const role = (profile?.role as string | undefined) ?? 'student';
      if (role === 'teacher' || role === 'admin') destination = '/teach';
    }
  } catch {
    // Role lookup failed — fall back to the student dashboard.
  }

  return NextResponse.redirect(new URL(destination, origin));
}
