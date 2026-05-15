'use client';

/**
 * MathContent — render mixed HTML + LaTeX math.
 *
 * Aria's lesson steps and her Q&A streaming responses contain math wrapped
 * in standard LaTeX delimiters:
 *
 *   - `$ ... $`   inline math
 *   - `$$ ... $$` display math
 *
 * This component walks the input string, splits on those delimiters, runs
 * the math segments through KaTeX, and trusts the HTML segments verbatim
 * (the upstream is our own Supabase content or our own Gemini stream;
 * we are not rendering arbitrary user input).
 *
 * Why a hand-rolled splitter and not `react-katex`:
 *  - `react-katex` requires you to know in advance which substring is math.
 *  - We get a freeform string with the math interleaved into prose + our own
 *    `<span class="hl-y">…</span>` highlights from the lesson schema.
 *  - A regex-based splitter handles the interleaving in one pass with no
 *    extra deps beyond `katex` itself.
 *
 * KaTeX errors render as a small red badge so authors notice broken LaTeX
 * during review instead of a silent crash.
 */
import katex from 'katex';
import 'katex/dist/katex.min.css';
import { useMemo, type ReactNode } from 'react';

import { cn } from '@/lib/utils';

interface MathContentProps {
  /** Mixed HTML + LaTeX. Math goes in `$...$` (inline) or `$$...$$` (display). */
  html: string;
  className?: string;
}

interface Segment {
  kind: 'html' | 'inline-math' | 'display-math';
  value: string;
}

// Tokenizes display math first ($$…$$) so its `$$` delimiters aren't mis-read
// as four inline-math markers. Non-greedy match; multiline-safe.
const DISPLAY_RE = /\$\$([\s\S]+?)\$\$/g;
const INLINE_RE = /\$([^$\n]+?)\$/g;

function tokenize(input: string): Segment[] {
  const out: Segment[] = [];
  let cursor = 0;

  const display = Array.from(input.matchAll(DISPLAY_RE));
  for (const m of display) {
    const inner = m[1];
    if (inner == null) continue;
    const start = m.index ?? 0;
    if (start > cursor) {
      const before = input.slice(cursor, start);
      out.push(...tokenizeInline(before));
    }
    out.push({ kind: 'display-math', value: inner.trim() });
    cursor = start + m[0].length;
  }
  if (cursor < input.length) {
    out.push(...tokenizeInline(input.slice(cursor)));
  }
  return out;
}

function tokenizeInline(input: string): Segment[] {
  const out: Segment[] = [];
  let cursor = 0;
  const inline = Array.from(input.matchAll(INLINE_RE));
  for (const m of inline) {
    const inner = m[1];
    if (inner == null) continue;
    const start = m.index ?? 0;
    if (start > cursor) {
      out.push({ kind: 'html', value: input.slice(cursor, start) });
    }
    out.push({ kind: 'inline-math', value: inner.trim() });
    cursor = start + m[0].length;
  }
  if (cursor < input.length) {
    out.push({ kind: 'html', value: input.slice(cursor) });
  }
  return out;
}

function renderMath(tex: string, displayMode: boolean): { html: string; error: string | null } {
  try {
    return {
      html: katex.renderToString(tex, {
        throwOnError: false,
        displayMode,
        strict: 'ignore',
        // Stick to a safe subset — we don't allow `\href`, `\includegraphics`,
        // or other extensions that could exfiltrate / load remote content.
        trust: false,
      }),
      error: null,
    };
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return { html: '', error: message };
  }
}

export function MathContent({ html, className }: MathContentProps) {
  const nodes = useMemo<ReactNode[]>(() => {
    const segments = tokenize(html);
    return segments.map((seg, i) => {
      if (seg.kind === 'html') {
        // The upstream string is our own authored / Gemini-generated content,
        // not user input. We render it as HTML so the existing
        // `<span class="hl-y">…</span>` highlights from the lesson schema
        // continue to work.
        return (
          <span
            key={i}
            // eslint-disable-next-line react/no-danger
            dangerouslySetInnerHTML={{ __html: seg.value }}
          />
        );
      }
      const displayMode = seg.kind === 'display-math';
      const { html: rendered, error } = renderMath(seg.value, displayMode);
      if (error) {
        return (
          <span
            key={i}
            title={error}
            className="rounded bg-coral-soft px-1 font-mono text-[0.85em] text-[#A1452B]"
          >
            ⚠ {seg.value}
          </span>
        );
      }
      const Wrapper = displayMode ? 'div' : 'span';
      return (
        <Wrapper
          key={i}
          className={displayMode ? 'my-2 overflow-x-auto' : undefined}
          // eslint-disable-next-line react/no-danger
          dangerouslySetInnerHTML={{ __html: rendered }}
        />
      );
    });
  }, [html]);

  return <span className={cn(className)}>{nodes}</span>;
}
