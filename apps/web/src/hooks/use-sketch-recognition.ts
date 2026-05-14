'use client';

import { useCallback, useRef } from 'react';

import type { RecognizedShape } from '@/hooks/use-socratic-aria';

export interface SketchPoint {
  /** Point coordinates in viewbox units: `[x, y]`. */
  0: number;
  1: number;
  length: 2;
}

export interface SketchStroke {
  color: string;
  /** Array of `[x, y]` tuples in viewbox units. */
  points: Array<[number, number]>;
}

/**
 * Crude geometric classifier — ported verbatim from the prototype.
 *
 * Returns one of: 'wave', 'horizontal-line', 'vertical-line',
 * 'diagonal-line', 'curve', 'circle', 'writing', 'sketch', or `null`
 * for strokes that are too small.
 */
export function recognizeStroke(stroke: SketchStroke | null | undefined): RecognizedShape {
  if (!stroke || !stroke.points || stroke.points.length < 2) return null;
  const pts = stroke.points;
  const xs = pts.map((p) => p[0]);
  const ys = pts.map((p) => p[1]);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const w = maxX - minX;
  const h = maxY - minY;
  const aspect = w / Math.max(1, h);

  // Tiny mark = probably writing component (digit/letter/dot)
  if (Math.max(w, h) < 40 && pts.length < 16) return 'writing';

  // Count direction changes in Y to detect wave-ness.
  let yChanges = 0;
  let lastDy = 0;
  for (let i = 2; i < pts.length; i++) {
    const cur = pts[i];
    const prev = pts[i - 1];
    if (!cur || !prev) continue;
    const dy = cur[1] - prev[1];
    if (Math.abs(dy) < 0.5) continue;
    const s = Math.sign(dy);
    if (lastDy !== 0 && s !== lastDy) yChanges++;
    lastDy = s;
  }

  if (yChanges >= 3 && w > 60) return 'wave';
  if (yChanges >= 1 && w > 40 && w > h * 1.5) return 'curve';

  if (aspect > 4 && h < 30) return 'horizontal-line';
  if (aspect < 0.25 && w < 30) return 'vertical-line';
  if (Math.max(w, h) > 50 && yChanges < 1) return 'diagonal-line';

  // Closed-ish? Start/end close + reasonable size.
  const first = pts[0];
  const last = pts[pts.length - 1];
  if (first && last) {
    const dx = first[0] - last[0];
    const dy = first[1] - last[1];
    const closingDist = Math.hypot(dx, dy);
    const span = Math.max(w, h);
    if (span > 30 && closingDist < span * 0.3) return 'circle';
  }

  return 'sketch';
}

/**
 * Roll consecutive 'writing' marks into a 'writing-cluster' so the
 * Socratic prompt can ask "looks like an equation?" rather than reacting
 * to each digit.
 */
export function aggregateRecognition(shapes: ReadonlyArray<RecognizedShape>): RecognizedShape {
  if (!shapes || shapes.length === 0) return null;
  const recent = shapes.slice(-6);
  const writingCount = recent.filter((s) => s === 'writing').length;
  if (writingCount >= 3) return 'writing-cluster';
  return shapes[shapes.length - 1] ?? null;
}

interface UseSketchRecognitionResult {
  /** Classify a new stroke and return the aggregated result. */
  recognize: (stroke: SketchStroke) => RecognizedShape;
  reset: () => void;
}

/**
 * Stateful wrapper that tracks the last few shapes for `aggregateRecognition`.
 */
export function useSketchRecognition(): UseSketchRecognitionResult {
  const historyRef = useRef<RecognizedShape[]>([]);

  const recognize = useCallback((stroke: SketchStroke): RecognizedShape => {
    const single = recognizeStroke(stroke);
    historyRef.current.push(single);
    if (historyRef.current.length > 12) {
      historyRef.current = historyRef.current.slice(-12);
    }
    return aggregateRecognition(historyRef.current);
  }, []);

  const reset = useCallback(() => {
    historyRef.current = [];
  }, []);

  return { recognize, reset };
}
