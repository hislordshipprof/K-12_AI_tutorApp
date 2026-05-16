import { getSupabaseBrowserClient } from '@/lib/supabase/client';

/**
 * Base URL of the FastAPI backend.
 *
 * Set via NEXT_PUBLIC_API_BASE (e.g. http://localhost:8000).
 */
const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? 'http://localhost:8000';

export class ApiError extends Error {
  public readonly status: number;
  public readonly body: unknown;

  constructor(message: string, status: number, body: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.body = body;
  }
}

export interface ApiOptions extends Omit<RequestInit, 'body' | 'headers'> {
  /** Plain object — will be JSON-serialised. Set `body` instead for raw payloads. */
  json?: unknown;
  body?: BodyInit | null;
  headers?: Record<string, string>;
  /** When true, omit the Authorization header even if a session exists. */
  anonymous?: boolean;
  /** Override the auth token (e.g. when called from a Server Action). */
  accessToken?: string;
}

async function resolveAuthToken(options: ApiOptions): Promise<string | undefined> {
  if (options.anonymous) return undefined;
  if (options.accessToken) return options.accessToken;

  if (typeof window === 'undefined') return undefined;

  try {
    const supabase = getSupabaseBrowserClient();
    const { data } = await supabase.auth.getSession();
    return data.session?.access_token;
  } catch {
    // Env vars missing or auth unavailable — fall through unauthenticated.
    return undefined;
  }
}

/**
 * Typed JSON fetch wrapper for the FastAPI backend.
 *
 * - Joins `path` onto NEXT_PUBLIC_API_BASE.
 * - Injects the Supabase session as a Bearer token when available.
 * - Sends `json` as a JSON body with the correct Content-Type.
 * - Parses JSON responses, returning `undefined` for 204.
 * - Throws `ApiError` on non-2xx with the parsed (or text) body.
 */
export async function api<T = unknown>(path: string, options: ApiOptions = {}): Promise<T> {
  const { json, body, headers, anonymous: _anonymous, accessToken: _accessToken, ...init } = options;

  const url = path.startsWith('http') ? path : `${API_BASE}${path.startsWith('/') ? '' : '/'}${path}`;

  const finalHeaders: Record<string, string> = {
    Accept: 'application/json',
    ...headers,
  };

  let finalBody = body;
  if (json !== undefined) {
    finalBody = JSON.stringify(json);
    finalHeaders['Content-Type'] ??= 'application/json';
  }

  const token = await resolveAuthToken(options);
  if (token && !finalHeaders.Authorization) {
    finalHeaders.Authorization = `Bearer ${token}`;
  }

  // Demo / preview mode: API has DEV_MODE=true and accepts an X-Dev-User-Id
  // header in lieu of a real JWT. We pin it to the seeded demo user so
  // session inserts satisfy the foreign-key constraint against auth.users.
  if (
    process.env.NEXT_PUBLIC_DEMO_MODE === 'true' &&
    !finalHeaders.Authorization &&
    !finalHeaders['X-Dev-User-Id']
  ) {
    finalHeaders['X-Dev-User-Id'] = '00000000-0000-0000-0000-000000000001';
  }

  const response = await fetch(url, {
    ...init,
    headers: finalHeaders,
    body: finalBody ?? null,
  });

  if (response.status === 204) {
    return undefined as T;
  }

  const contentType = response.headers.get('content-type') ?? '';
  const parsed: unknown = contentType.includes('application/json')
    ? await response.json().catch(() => undefined)
    : await response.text().catch(() => undefined);

  if (!response.ok) {
    const message =
      (parsed && typeof parsed === 'object' && 'detail' in parsed && typeof (parsed as { detail: unknown }).detail === 'string'
        ? (parsed as { detail: string }).detail
        : undefined) ?? `API ${response.status} ${response.statusText}`;
    throw new ApiError(message, response.status, parsed);
  }

  return parsed as T;
}

export const apiBase = API_BASE;

/**
 * Resolve a real classroom topic to link to when the caller has no
 * specific topic in hand (the dashboard "Resume lesson" fallback, the
 * marketing "Watch demo" links, the rail's Classroom entry).
 *
 * Previously these all pointed at the `wave-properties-anatomy` prototype
 * slug, which has no row in `topics` — `POST /v1/sessions` then failed the
 * `lesson_sessions_topic_id_fkey` FK. We instead resolve the first real
 * seeded topic from the AP Physics 1 curriculum so every classroom session
 * is created against a real DB topic UUID.
 *
 * Returns `/classroom/{topicUuid}` on success, or `null` when the
 * curriculum can't be reached (caller decides the fallback).
 */
export async function resolveClassroomTopicPath(): Promise<string | null> {
  try {
    const units = await api<
      { id: string; topics: { id: string }[] }[]
    >('/v1/courses/ap-physics-1/units');
    for (const unit of units) {
      const topic = unit.topics?.[0];
      if (topic?.id) return `/classroom/${topic.id}`;
    }
  } catch {
    // Curriculum unavailable — let the caller fall back.
  }
  return null;
}
