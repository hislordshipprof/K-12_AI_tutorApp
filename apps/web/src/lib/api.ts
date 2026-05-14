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
