'use client';

import { useMutation } from '@tanstack/react-query';
import { useEffect, useState } from 'react';

import { api, type ApiError } from '@/lib/api';

interface SessionOut {
  id: string;
  user_id: string;
  topic_id: string;
  started_at: string;
  ended_at: string | null;
  agent_state: Record<string, unknown>;
  created_at: string;
}

interface UseSessionResult {
  sessionId: string | null;
  isLoading: boolean;
  /** Set when the API call failed; we still surface a local fallback id. */
  error: Error | null;
}

/**
 * Stable v4-ish UUID built from `crypto.randomUUID` when available, with
 * a Math.random fallback. Used both as a synthetic topic UUID (the API
 * expects UUIDs but our routes use slugs) and as a fallback session id.
 */
function randomUUID(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    try {
      return crypto.randomUUID();
    } catch {
      // fall through
    }
  }
  // RFC4122-ish fallback — adequate for client-side session identifiers
  // when crypto.randomUUID is unavailable (older WebViews).
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

/**
 * Deterministic UUID derived from a topic slug.
 *
 * The Sessions API expects `topic_id: UUID` but our public URLs use
 * slugs (`wave-properties-anatomy`). We hash the slug into a v4-looking
 * UUID so the same slug always produces the same id within a session.
 */
function topicSlugToUuid(slug: string): string {
  // FNV-1a 32-bit hash, repeated four times with different starting offsets
  // for entropy in each chunk. Not cryptographic — just deterministic.
  const hash = (s: string, offset: number): string => {
    let h = 0x811c9dc5 ^ offset;
    for (let i = 0; i < s.length; i++) {
      h ^= s.charCodeAt(i);
      h = (h + ((h << 1) + (h << 4) + (h << 7) + (h << 8) + (h << 24))) >>> 0;
    }
    return h.toString(16).padStart(8, '0');
  };
  const a = hash(slug, 0);
  const b = hash(slug, 1).slice(0, 4);
  const c = '4' + hash(slug, 2).slice(0, 3);
  const d = '8' + hash(slug, 3).slice(0, 3);
  const e = (hash(slug, 4) + hash(slug, 5)).slice(0, 12);
  return `${a}-${b}-${c}-${d}-${e}`;
}

/**
 * Start a lesson session on the API.
 *
 * Fires a `POST /v1/sessions` once on mount. On failure (unauthenticated,
 * offline, API down) we fall back to a local synthetic session id so the
 * UI keeps working. The Socratic Q&A endpoint accepts any UUID in dev mode.
 */
export function useSession(topicSlug: string): UseSessionResult {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [error, setError] = useState<Error | null>(null);

  const startMut = useMutation<SessionOut, ApiError | Error, string>({
    mutationFn: async (slug: string) => {
      const topicUuid = topicSlugToUuid(slug);
      return await api<SessionOut>('/v1/sessions', {
        method: 'POST',
        json: { topic_id: topicUuid },
      });
    },
    onSuccess: (data) => {
      setSessionId(data.id);
    },
    onError: (e) => {
      // Fall back to a client-side id so the UI keeps working.
      setError(e);
      setSessionId(randomUUID());
    },
  });

  useEffect(() => {
    if (!topicSlug || startMut.isPending || sessionId) return;
    startMut.mutate(topicSlug);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [topicSlug]);

  return {
    sessionId,
    isLoading: startMut.isPending && sessionId === null,
    error,
  };
}
