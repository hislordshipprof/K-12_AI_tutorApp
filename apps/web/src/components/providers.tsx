'use client';

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import {
  createContext,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import { Toaster } from 'sonner';
import type { SupabaseClient } from '@supabase/supabase-js';

import { AuthProvider } from '@/components/auth-provider';
import { getSupabaseBrowserClient } from '@/lib/supabase/client';

const SupabaseContext = createContext<SupabaseClient | null>(null);

/**
 * Access the shared browser Supabase client.
 *
 * Returns `null` if env vars are missing — call sites should guard before
 * dereferencing rather than assuming a client is always present.
 */
export function useSupabase(): SupabaseClient | null {
  return useContext(SupabaseContext);
}

function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        refetchOnWindowFocus: false,
        retry: 1,
      },
    },
  });
}

export interface ProvidersProps {
  children: ReactNode;
}

/**
 * Root client providers — React Query, Supabase, and sonner toasts.
 */
export function Providers({ children }: ProvidersProps) {
  const [queryClient] = useState(makeQueryClient);

  const supabase = useMemo<SupabaseClient | null>(() => {
    try {
      return getSupabaseBrowserClient();
    } catch {
      // Missing env vars during scaffolding — render without auth.
      return null;
    }
  }, []);

  return (
    <SupabaseContext.Provider value={supabase}>
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          {children}
          <Toaster position="top-center" richColors closeButton />
        </AuthProvider>
      </QueryClientProvider>
    </SupabaseContext.Provider>
  );
}
