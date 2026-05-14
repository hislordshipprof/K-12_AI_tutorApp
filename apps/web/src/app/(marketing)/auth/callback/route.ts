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
 * destination — defaulting to `/dashboard`.
 */
export async function GET(request: NextRequest) {
  const { searchParams, origin } = request.nextUrl;
  const code = searchParams.get('code');
  const next = searchParams.get('next') ?? '/dashboard';

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

  return NextResponse.redirect(new URL(next, origin));
}
