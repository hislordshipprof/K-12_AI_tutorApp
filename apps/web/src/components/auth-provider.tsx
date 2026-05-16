'use client';

import { useRouter } from 'next/navigation';
import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import type { Session, User } from '@supabase/supabase-js';

import { useSupabase } from '@/components/providers';

interface AuthContextValue {
  /** The authenticated user, or `null` when signed out / still loading. */
  user: User | null;
  /** The active Supabase session, or `null` when signed out. */
  session: Session | null;
  /** True until the initial session lookup resolves. */
  loading: boolean;
  /** Sign the current user out and send them to the sign-in page. */
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue>({
  user: null,
  session: null,
  loading: true,
  signOut: async () => {},
});

/**
 * Access the current authenticated user.
 *
 * `user`/`session` are `null` while `loading` is true and whenever there is
 * no session. Call sites should branch on `loading` before treating a
 * `null` user as "signed out".
 */
export function useAuth(): AuthContextValue {
  return useContext(AuthContext);
}

/**
 * Tracks the Supabase auth session client-side so the app always knows the
 * current user. Subscribes to `onAuthStateChange` so sign-in / sign-out /
 * token-refresh propagate to every consumer without a reload.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const supabase = useSupabase();
  const router = useRouter();
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!supabase) {
      // Supabase env vars missing — render signed-out and stop loading.
      setLoading(false);
      return;
    }

    let active = true;

    supabase.auth.getSession().then(({ data }) => {
      if (!active) return;
      setSession(data.session);
      setLoading(false);
    });

    const { data: sub } = supabase.auth.onAuthStateChange((_event, next) => {
      setSession(next);
      setLoading(false);
    });

    return () => {
      active = false;
      sub.subscription.unsubscribe();
    };
  }, [supabase]);

  const value = useMemo<AuthContextValue>(
    () => ({
      user: session?.user ?? null,
      session,
      loading,
      async signOut() {
        if (supabase) {
          await supabase.auth.signOut();
        }
        router.push('/login');
        router.refresh();
      },
    }),
    [session, loading, supabase, router],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
