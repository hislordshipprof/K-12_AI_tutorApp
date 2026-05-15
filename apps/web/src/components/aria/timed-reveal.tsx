'use client';

/**
 * TimedReveal — renders mixed HTML + LaTeX where each word "writes itself"
 * onto the page in time with Aria's voice (Phase A of the live-drawing
 * work).
 *
 * Given a `progress` value 0→1 (driven by `useTtsPlayback().progress`,
 * which tracks the TTS audio clock), words ahead of the playhead are dim
 * and the word at the playhead gets a soft chalk-glow, so the student
 * sees the explanation appear as it is spoken rather than all at once.
 *
 * Tokenisation reuses MathContent's `$...$` / `$$...$$` splitter, then
 * each prose segment is parsed with DOMParser so the lesson schema's
 * `<span class="hl-*">`, `<em>`, `<strong>`, `<code>` wrappers survive —
 * every text word becomes one independently-revealed atom; every math
 * span is one atom.
 *
 * SSR-safe: DOMParser only exists in the browser, so on the server (and
 * the very first client render) we fall back to rendering everything
 * revealed. The audio-synced reveal kicks in once mounted.
 */
import katex from 'katex';
import 'katex/dist/katex.min.css';
import { useEffect, useMemo, useState } from 'react';

import { cn } from '@/lib/utils';

interface TimedRevealProps {
  /** Mixed HTML + LaTeX. Same shape as MathContent's `html` prop. */
  html: string;
  /** 0→1 playback progress. 1 (or omitted) renders everything revealed. */
  progress?: number;
  className?: string;
}

interface Segment {
  kind: 'html' | 'inline-math' | 'display-math';
  value: string;
}

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
    if (start > cursor) out.push(...tokenizeInline(input.slice(cursor, start)));
    out.push({ kind: 'display-math', value: inner.trim() });
    cursor = start + m[0].length;
  }
  if (cursor < input.length) out.push(...tokenizeInline(input.slice(cursor)));
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
    if (start > cursor) out.push({ kind: 'html', value: input.slice(cursor, start) });
    out.push({ kind: 'inline-math', value: inner.trim() });
    cursor = start + m[0].length;
  }
  if (cursor < input.length) out.push({ kind: 'html', value: input.slice(cursor) });
  return out;
}

function renderMath(tex: string, displayMode: boolean): string {
  try {
    return katex.renderToString(tex, {
      throwOnError: false,
      displayMode,
      strict: 'ignore',
      trust: false,
    });
  } catch {
    return tex;
  }
}

/** One reveal unit. `weight` ≈ how long it takes to say (chars, min 1). */
interface Atom {
  /** Pre-rendered HTML for this atom (a word, or a KaTeX math fragment). */
  inner: string;
  /** Inline wrapper class from the lesson schema, if any. */
  wrapClass?: string;
  /** Wrapper tag — span / em / strong / code. */
  tag: 'span' | 'em' | 'strong' | 'code';
  weight: number;
  /** True for whitespace-only atoms — always shown, never highlighted. */
  isSpace: boolean;
}

const HL_CLASS_RE = /^hl-[ybpg]$/;

/** Walk a parsed DOM node, emitting one Atom per word / element. */
function walkNode(
  node: ChildNode,
  wrapClass: string | undefined,
  tag: Atom['tag'],
  atoms: Atom[],
): void {
  if (node.nodeType === Node.TEXT_NODE) {
    const text = node.textContent ?? '';
    // Split keeping the whitespace as its own tokens so layout is intact.
    for (const piece of text.split(/(\s+)/)) {
      if (piece.length === 0) continue;
      const isSpace = /^\s+$/.test(piece);
      atoms.push({
        inner: piece,
        wrapClass,
        tag,
        weight: isSpace ? 0 : Math.max(1, piece.length),
        isSpace,
      });
    }
    return;
  }
  if (node.nodeType === Node.ELEMENT_NODE) {
    const el = node as HTMLElement;
    const tagName = el.tagName.toLowerCase();
    let nextWrap = wrapClass;
    let nextTag: Atom['tag'] = tag;
    if (tagName === 'span') {
      const cls = el.getAttribute('class') ?? '';
      if (HL_CLASS_RE.test(cls)) nextWrap = cls;
    } else if (tagName === 'em' || tagName === 'strong' || tagName === 'code') {
      nextTag = tagName;
    }
    for (const child of Array.from(el.childNodes)) {
      walkNode(child, nextWrap, nextTag, atoms);
    }
  }
}

export function TimedReveal({ html, progress = 1, className }: TimedRevealProps) {
  // DOMParser is browser-only — render fully-revealed until mounted.
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  const atoms = useMemo<Atom[]>(() => {
    if (typeof window === 'undefined' || !window.DOMParser) return [];
    const segments = tokenize(html);
    const out: Atom[] = [];
    const parser = new DOMParser();
    for (const seg of segments) {
      if (seg.kind === 'html') {
        const doc = parser.parseFromString(`<body>${seg.value}</body>`, 'text/html');
        const body = doc.body;
        for (const child of Array.from(body.childNodes)) {
          walkNode(child, undefined, 'span', out);
        }
      } else {
        const displayMode = seg.kind === 'display-math';
        out.push({
          inner: renderMath(seg.value, displayMode),
          tag: 'span',
          weight: Math.max(3, seg.value.length),
          isSpace: false,
        });
      }
    }
    return out;
  }, [html]);

  const totalWeight = useMemo(
    () => atoms.reduce((sum, a) => sum + a.weight, 0) || 1,
    [atoms],
  );

  // Compute the cumulative-weight cutoff for the current playhead.
  const revealedThreshold = progress * totalWeight;

  if (!mounted || atoms.length === 0) {
    // SSR / pre-mount fallback — render the raw mixed content fully.
    return (
      <span
        className={cn(className)}
        // eslint-disable-next-line react/no-danger
        dangerouslySetInnerHTML={{ __html: html }}
      />
    );
  }

  let cumulative = 0;
  return (
    <span className={cn(className)}>
      {atoms.map((atom, i) => {
        const start = cumulative;
        cumulative += atom.weight;
        const end = cumulative;
        // Whitespace is always present so wrapping doesn't jump around.
        if (atom.isSpace) {
          return <span key={i}>{atom.inner}</span>;
        }
        const revealed = progress >= 1 || end <= revealedThreshold;
        const isCurrent =
          progress < 1 &&
          revealedThreshold >= start &&
          revealedThreshold < end;
        const Tag = atom.tag;
        return (
          <Tag
            key={i}
            className={atom.wrapClass}
            style={{
              opacity: revealed ? 1 : 0.18,
              filter: revealed ? 'none' : 'blur(0.6px)',
              textShadow: isCurrent
                ? '0 0 10px rgba(255,235,160,0.55)'
                : undefined,
              transition: 'opacity .28s ease, filter .28s ease',
            }}
            // eslint-disable-next-line react/no-danger
            dangerouslySetInnerHTML={{ __html: atom.inner }}
          />
        );
      })}
    </span>
  );
}
