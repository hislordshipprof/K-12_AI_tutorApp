/**
 * Scene contract — the interface every animated chalkboard scene implements
 * (Phase B of the live-drawing work).
 *
 * A "scene" is a parametric SVG diagram that draws itself in time with
 * Aria's voice: a free-body diagram, a projectile arc, a number line, etc.
 * The lesson generator tags each step with an optional `scene: {type,
 * params}`; the classroom looks the `type` up in SCENE_REGISTRY and
 * renders the matching component, feeding it the live audio progress.
 *
 * ## Rendering contract
 *
 * A SceneComponent returns SVG content (a `<g>` or fragment of SVG
 * elements) sized to a **900 × 530 viewBox**. It is mounted INSIDE the
 * whiteboard's `<svg>`, which already provides:
 *   - `<filter id="chalk">`  — chalk-texture turbulence/displacement
 *   - `<filter id="glow">`   — soft glow for emphasised strokes
 * Scenes SHOULD apply `filter="url(#chalk)"` to strokes for the chalk look.
 *
 * ## Animation contract
 *
 * Scenes receive `progress` (0→1, the TTS audio clock). At progress 0 the
 * board is blank; at progress 1 the full diagram is drawn. Elements should
 * appear sequentially as progress climbs — use `revealWindow()` to map a
 * sub-range of the timeline to each element, and the `chalkStroke()`
 * helper for "drawing" line/path strokes.
 *
 * Scenes MUST be pure + deterministic in `(progress, params)` and MUST NOT
 * use timers, network, or local state — the audio clock is the only clock.
 */
import type { FC } from 'react';

export interface SceneProps {
  /** 0→1 TTS audio-clock progress. The only animation driver. */
  progress: number;
  /** Scene-specific config from the lesson step's `scene.params`. */
  params: Record<string, unknown>;
}

/** A scene renders SVG content sized to the 900×530 whiteboard viewBox. */
export type SceneComponent = FC<SceneProps>;

// ── Shared chalk palette (matches the CSS custom props the board uses) ──────
export const CHALK = {
  white: 'var(--chalk, #f4f1e8)',
  blue: 'var(--chalk-blue, #a8c4e8)',
  yellow: 'var(--chalk-yellow, #f5e067)',
  pink: 'var(--chalk-pink, #f09aaf)',
  green: 'var(--chalk-green, #7dd4a8)',
  faint: 'rgba(255,255,255,.18)',
} as const;

// ── Animation helpers ───────────────────────────────────────────────────────

/**
 * Map the global `progress` (0→1) onto a sub-window `[start, end]`, returning
 * a local 0→1 for that element. Before `start` → 0; after `end` → 1.
 *
 * Lets a scene sequence elements: e.g. the axis draws over [0, .25], the
 * first point over [.25, .4], the label over [.4, .5], etc.
 */
export function revealWindow(
  progress: number,
  start: number,
  end: number,
): number {
  if (end <= start) return progress >= end ? 1 : 0;
  return Math.max(0, Math.min(1, (progress - start) / (end - start)));
}

/**
 * Stroke-draw props for a path/line of total length `len`. Spread the
 * result onto an SVG `<path>` / `<line>` to make it "draw on" as `local`
 * goes 0→1 (use `revealWindow` to compute `local`).
 *
 *   <path d={...} {...chalkStroke(pathLength, revealWindow(progress, 0, .3))} />
 */
export function chalkStroke(
  len: number,
  local: number,
): { strokeDasharray: number; strokeDashoffset: number } {
  return {
    strokeDasharray: len,
    strokeDashoffset: len * (1 - Math.max(0, Math.min(1, local))),
  };
}

/** Opacity that fades in across a reveal window. Convenience over revealWindow. */
export function fadeIn(progress: number, start: number, end: number): number {
  return revealWindow(progress, start, end);
}

// ── Param coercion helpers — scenes get untrusted `params` from the DB ──────
export function numParam(
  params: Record<string, unknown>,
  key: string,
  fallback: number,
): number {
  const v = params[key];
  return typeof v === 'number' && Number.isFinite(v) ? v : fallback;
}

export function strParam(
  params: Record<string, unknown>,
  key: string,
  fallback: string,
): string {
  const v = params[key];
  return typeof v === 'string' && v.length > 0 ? v : fallback;
}

export function arrParam<T = unknown>(
  params: Record<string, unknown>,
  key: string,
  fallback: T[],
): T[] {
  const v = params[key];
  return Array.isArray(v) ? (v as T[]) : fallback;
}
