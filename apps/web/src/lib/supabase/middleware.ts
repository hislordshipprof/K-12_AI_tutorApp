import { createServerClient, type CookieOptions } from '@supabase/ssr';
import { NextResponse, type NextRequest } from 'next/server';

interface CookiePayload {
  name: string;
  value: string;
  options: CookieOptions;
}

/**
 * Refresh the Supabase auth session inside Next.js middleware.
 *
 * Follows the official @supabase/ssr cookies pattern: a `getAll`/`setAll`
 * pair bound to both the inbound request cookies and the outbound response
 * cookies, so a refreshed session is propagated back to the browser on the
 * very next request.
 *
 * Returns an object containing the (possibly-mutated) `NextResponse` and the
 * current user (or `null` when there is no session). The caller is
 * responsible for deciding what to do with the user — e.g. redirecting
 * unauthenticated requests away from gated routes.
 */
export async function updateSupabaseSession(request: NextRequest) {
  let response = NextResponse.next({
    request: {
      headers: request.headers,
    },
  });

  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

  // If env vars are missing (e.g. local scaffolding without Supabase wired
  // up yet) skip session refresh entirely and act as if the user is signed
  // out. This keeps `next dev` from crashing on a fresh checkout.
  if (!url || !anonKey) {
    return { response, user: null as null };
  }

  const supabase = createServerClient(url, anonKey, {
    cookies: {
      getAll() {
        return request.cookies.getAll();
      },
      setAll(cookiesToSet: CookiePayload[]) {
        for (const { name, value } of cookiesToSet) {
          request.cookies.set(name, value);
        }
        response = NextResponse.next({
          request: {
            headers: request.headers,
          },
        });
        for (const { name, value, options } of cookiesToSet) {
          response.cookies.set(name, value, options);
        }
      },
    },
  });

  // IMPORTANT: do not run any code between createServerClient and
  // supabase.auth.getUser() — it could cause subtle issues with users
  // being logged out unexpectedly.
  const {
    data: { user },
  } = await supabase.auth.getUser();

  return { response, user };
}
