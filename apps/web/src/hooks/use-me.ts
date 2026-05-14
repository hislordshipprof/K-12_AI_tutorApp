/**
 * React Query hook for the current user — profile + dashboard stats.
 *
 * Calls `GET /v1/me`. Returns `null` when the user is not authenticated
 * (the API responds 401, which we treat as "no session" rather than an
 * error). Pages should render an empty/scaffolding state in that case
 * instead of fake placeholder values.
 */
import { useQuery } from '@tanstack/react-query';

import { api, ApiError } from '@/lib/api';

export interface MeStats {
  topics_done: number;
  time_spent_min: number;
  quiz_avg_pct: number | null;
}

export interface MeProfile {
  id: string;
  full_name: string | null;
  avatar_color: string;
  streak_days: number;
  stats: MeStats;
}

export function useMe() {
  return useQuery<MeProfile | null>({
    queryKey: ['me'],
    queryFn: async () => {
      try {
        return await api<MeProfile>('/v1/me');
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) return null;
        throw err;
      }
    },
    staleTime: 60_000,
    retry: 1,
  });
}

/** Best-effort display name. Returns "there" so greetings still read naturally. */
export function displayName(me: MeProfile | null | undefined): string {
  if (!me?.full_name) return 'there';
  return me.full_name.split(/\s+/)[0] ?? 'there';
}
