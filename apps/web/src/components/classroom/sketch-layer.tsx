'use client';

import { getStroke } from 'perfect-freehand';
import { useEffect, useRef, useState } from 'react';
import type { PointerEvent as ReactPointerEvent } from 'react';

import type { SketchStroke } from '@/hooks/use-sketch-recognition';
import { cn } from '@/lib/utils';

export interface SketchApi {
  clear?: () => void;
  undo?: () => void;
  count?: number;
}

interface SketchLayerProps {
  active: boolean;
  color: string;
  eraser: boolean;
  /** Mutable ref-like object the parent can hold to issue clear/undo. */
  strokesApi?: SketchApi;
  onStrokeStart?: () => void;
  onStrokeEnd?: (stroke: SketchStroke) => void;
}

/**
 * Convert perfect-freehand's variable-width polygon points into an
 * SVG path that closes the loop (creates a tapered chalk stroke).
 */
function pointsToPath(points: number[][]): string {
  if (!points || points.length === 0) return '';
  if (points.length < 2) {
    const p = points[0];
    if (!p) return '';
    return `M${p[0]},${p[1]}L${(p[0] ?? 0) + 0.1},${(p[1] ?? 0) + 0.1}`;
  }
  let d = `M${points[0]?.[0] ?? 0},${points[0]?.[1] ?? 0}`;
  for (let i = 1; i < points.length; i++) {
    const cur = points[i];
    if (!cur) continue;
    d += `L${cur[0]},${cur[1]}`;
  }
  d += 'Z';
  return d;
}

const ERASE_TOKEN = '__erase__';

/**
 * Overlay SVG that captures pointer events when `active` and renders
 * variable-width chalk strokes via perfect-freehand + a turbulence filter.
 *
 * Re-renders on every pointer move with a fresh snapshot of the in-flight
 * stroke so the user sees their line follow the cursor.
 */
export function SketchLayer({
  active,
  color,
  eraser,
  strokesApi,
  onStrokeStart,
  onStrokeEnd,
}: SketchLayerProps) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [strokes, setStrokes] = useState<SketchStroke[]>([]);
  const drawingRef = useRef<SketchStroke | null>(null);

  // Expose API to parent on every state change.
  useEffect(() => {
    if (!strokesApi) return;
    strokesApi.clear = () => setStrokes([]);
    strokesApi.undo = () => setStrokes((s) => s.slice(0, -1));
    strokesApi.count = strokes.length;
  }, [strokes, strokesApi]);

  const toPoint = (e: ReactPointerEvent<SVGSVGElement>): [number, number] => {
    const svg = svgRef.current;
    if (!svg) return [0, 0];
    const pt = svg.createSVGPoint();
    pt.x = e.clientX;
    pt.y = e.clientY;
    const ctm = svg.getScreenCTM();
    if (!ctm) return [0, 0];
    const p = pt.matrixTransform(ctm.inverse());
    return [p.x, p.y];
  };

  const onDown = (e: ReactPointerEvent<SVGSVGElement>) => {
    if (!active) return;
    e.preventDefault();
    (e.target as Element).setPointerCapture?.(e.pointerId);
    const start = toPoint(e);
    const stroke: SketchStroke = {
      color: eraser ? ERASE_TOKEN : color,
      points: [start],
    };
    drawingRef.current = stroke;
    setStrokes((s) => [...s, { color: stroke.color, points: [...stroke.points] }]);
    onStrokeStart?.();
  };

  const onMove = (e: ReactPointerEvent<SVGSVGElement>) => {
    const cur = drawingRef.current;
    if (!cur) return;
    cur.points.push(toPoint(e));
    const snapshot: SketchStroke = { color: cur.color, points: [...cur.points] };
    setStrokes((s) => {
      if (s.length === 0) return s;
      const copy = s.slice(0, -1);
      copy.push(snapshot);
      return copy;
    });
  };

  const onUp = () => {
    const cur = drawingRef.current;
    if (cur) {
      onStrokeEnd?.(cur);
      drawingRef.current = null;
    }
  };

  return (
    <svg
      ref={svgRef}
      className={cn('sketch-layer', active && 'active')}
      viewBox="0 0 1200 700"
      preserveAspectRatio="xMidYMid meet"
      onPointerDown={onDown}
      onPointerMove={onMove}
      onPointerUp={onUp}
      onPointerLeave={onUp}
    >
      <defs>
        <filter id="sketch-chalk">
          <feTurbulence
            type="fractalNoise"
            baseFrequency=".62"
            numOctaves="3"
            stitchTiles="stitch"
            result="n"
          />
          <feDisplacementMap
            in="SourceGraphic"
            in2="n"
            scale="1.4"
            xChannelSelector="R"
            yChannelSelector="G"
          />
        </filter>
      </defs>
      {strokes
        .filter((s) => s.color !== ERASE_TOKEN)
        .map((s, i) => {
          // perfect-freehand expects [x, y, pressure?] tuples. We let it
          // synthesize pressure from velocity.
          const outline = getStroke(s.points, {
            size: 4,
            thinning: 0.5,
            smoothing: 0.5,
            streamline: 0.35,
            simulatePressure: true,
            last: drawingRef.current !== null && i === strokes.length - 1 ? false : true,
          });
          const d = pointsToPath(outline);
          return (
            <path
              key={i}
              d={d}
              fill={s.color}
              stroke={s.color}
              strokeWidth={0.5}
              filter="url(#sketch-chalk)"
              opacity={0.92}
            />
          );
        })}
    </svg>
  );
}
