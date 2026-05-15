/**
 * Lightweight Server-Sent Events helper.
 *
 * The FastAPI `/v1/sessions/{id}/qa` and `/sessions/{id}/sketch` endpoints
 * emit `data: {...json...}\n\n` frames. We use POST + a streaming `fetch`
 * reader (the native EventSource only supports GET) and parse the frames
 * by splitting on the `\n\n` separator.
 *
 * Yields each parsed JSON payload. Unparseable frames are silently skipped
 * so a single bad chunk doesn't kill the whole stream.
 */
import { apiBase } from '@/lib/api';
import { getSupabaseBrowserClient } from '@/lib/supabase/client';

export interface SSEInit extends Omit<RequestInit, 'body'> {
  json?: unknown;
  body?: BodyInit | null;
  /** Skip the Supabase bearer header even if a session exists. */
  anonymous?: boolean;
}

async function resolveBearer(anonymous: boolean | undefined): Promise<string | undefined> {
  if (anonymous) return undefined;
  if (typeof window === 'undefined') return undefined;
  try {
    const supabase = getSupabaseBrowserClient();
    const { data } = await supabase.auth.getSession();
    return data.session?.access_token;
  } catch {
    return undefined;
  }
}

/**
 * Open an SSE stream and yield each parsed JSON event payload.
 *
 * The caller controls the request body / method via `init.json` or
 * `init.body`. Stream errors are surfaced by throwing.
 */
export async function* streamSSE<T = unknown>(
  path: string,
  init: SSEInit = {},
): AsyncGenerator<T, void, void> {
  const url = path.startsWith('http') ? path : `${apiBase}${path.startsWith('/') ? '' : '/'}${path}`;

  const headers: Record<string, string> = {
    Accept: 'text/event-stream',
    ...(init.headers as Record<string, string> | undefined),
  };

  let body = init.body ?? null;
  if (init.json !== undefined) {
    body = JSON.stringify(init.json);
    headers['Content-Type'] ??= 'application/json';
  }

  const token = await resolveBearer(init.anonymous);
  if (token && !headers.Authorization) {
    headers.Authorization = `Bearer ${token}`;
  }

  // Demo / preview mode: mirror lib/api.ts — the API runs DEV_MODE=true and
  // accepts an X-Dev-User-Id header in lieu of a real JWT. Without this an
  // unauthenticated SSE call (no Supabase session) 401s.
  if (
    process.env.NEXT_PUBLIC_DEMO_MODE === 'true' &&
    !headers.Authorization &&
    !headers['X-Dev-User-Id']
  ) {
    headers['X-Dev-User-Id'] = '00000000-0000-0000-0000-000000000001';
  }

  const { json: _json, anonymous: _anonymous, body: _body, headers: _headers, ...rest } = init;
  void _json;
  void _anonymous;
  void _body;
  void _headers;

  const res = await fetch(url, {
    method: 'POST',
    ...rest,
    headers,
    body,
  });

  if (!res.ok) {
    const detail = await res.text().catch(() => '');
    throw new Error(`SSE request failed: ${res.status} ${res.statusText}${detail ? ` — ${detail}` : ''}`);
  }
  if (!res.body) {
    throw new Error('SSE response has no body');
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });

      // SSE frames are separated by a blank line. Split, keep the trailing
      // partial frame in the buffer for the next chunk.
      const frames = buf.split('\n\n');
      buf = frames.pop() ?? '';

      for (const frame of frames) {
        // A frame may have multiple `field: value` lines; we only care about `data:`.
        for (const line of frame.split('\n')) {
          if (!line.startsWith('data:')) continue;
          const raw = line.slice(5).trim();
          if (!raw) continue;
          try {
            yield JSON.parse(raw) as T;
          } catch {
            // Skip malformed chunk.
          }
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}
