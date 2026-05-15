/**
 * MotionGraphScene — an x-t / v-t style line graph that draws its axes,
 * gridlines and curve in sequence with the audio.
 *
 * params:
 *   title?:  string
 *   xLabel?: string  (default "time")
 *   yLabel?: string  (default "position")
 *   curve?:  'linear'|'parabola'|'flat'|'sine'  (default "linear")
 *   points?: { label:string; x:number; y:number }[]
 *            x,y are 0→1 fractions of the plot area
 *
 * Drawing timeline:
 *   [0,   .22]  axes + arrowheads draw on (axis labels fade with them)
 *   [.18, .30]  faint gridlines fade in
 *   [.30, .82]  the curve draws on left→right
 *   [.82, 1.0]  marked points (dot + label) appear in sequence
 */
import {
  CHALK,
  chalkStroke,
  revealWindow,
  strParam,
  type SceneComponent,
} from './types';

// Plot area within the 900×530 viewBox.
const PX0 = 130; // left (y-axis)
const PX1 = 800; // right
const PY0 = 110; // top
const PY1 = 410; // bottom (x-axis)
const PLOT_W = PX1 - PX0;
const PLOT_H = PY1 - PY0;

type Curve = 'linear' | 'parabola' | 'flat' | 'sine';
const CURVES: Curve[] = ['linear', 'parabola', 'flat', 'sine'];

interface MarkPoint {
  label: string;
  x: number;
  y: number;
}

export const MotionGraphScene: SceneComponent = ({ progress, params }) => {
  const title = strParam(params, 'title', '');
  const xLabel = strParam(params, 'xLabel', 'time');
  const yLabel = strParam(params, 'yLabel', 'position');

  const rawCurve = strParam(params, 'curve', 'linear');
  const curve: Curve = CURVES.includes(rawCurve as Curve)
    ? (rawCurve as Curve)
    : 'linear';

  const rawPoints = Array.isArray(params.points) ? params.points : [];
  const points: MarkPoint[] = rawPoints
    .filter(
      (p): p is MarkPoint =>
        !!p &&
        typeof p === 'object' &&
        typeof (p as MarkPoint).x === 'number' &&
        typeof (p as MarkPoint).y === 'number',
    )
    .slice(0, 6);

  // Convert plot-fraction (0→1, y up) → SVG coords.
  const toX = (fx: number) => PX0 + Math.max(0, Math.min(1, fx)) * PLOT_W;
  const toY = (fy: number) => PY1 - Math.max(0, Math.min(1, fy)) * PLOT_H;

  // Curve value: fraction y for a given fraction x (0→1).
  const curveY = (fx: number): number => {
    switch (curve) {
      case 'parabola':
        return fx * fx;
      case 'flat':
        return 0.5;
      case 'sine':
        return 0.5 + 0.4 * Math.sin(fx * Math.PI * 2);
      case 'linear':
      default:
        return fx;
    }
  };

  // Sample the curve into a polyline so we can compute length + draw it on.
  const SAMPLES = 72;
  const curvePts: { x: number; y: number }[] = [];
  for (let i = 0; i <= SAMPLES; i++) {
    const fx = i / SAMPLES;
    curvePts.push({ x: toX(fx), y: toY(curveY(fx)) });
  }
  let curveLen = 0;
  for (let i = 1; i < curvePts.length; i++) {
    const a = curvePts[i - 1];
    const b = curvePts[i];
    if (!a || !b) continue;
    curveLen += Math.hypot(b.x - a.x, b.y - a.y);
  }
  const curvePath = curvePts
    .map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x} ${p.y}`)
    .join(' ');

  const axisLocal = revealWindow(progress, 0, 0.22);
  const curveLocal = revealWindow(progress, 0.3, 0.82);

  // Gridlines at quarter fractions.
  const gridFracs = [0.25, 0.5, 0.75];

  return (
    <g>
      {/* Title */}
      {title ? (
        <text
          x="450"
          y="70"
          textAnchor="middle"
          fill={CHALK.white}
          fontSize="26"
          fontFamily="Bricolage Grotesque, serif"
          fontStyle="italic"
          filter="url(#chalk)"
          opacity={revealWindow(progress, 0, 0.12)}
        >
          {title}
        </text>
      ) : null}

      {/* Gridlines — faint, fade in over [.18,.3] */}
      {gridFracs.map((f, i) => {
        const local = revealWindow(progress, 0.18, 0.3);
        return (
          <g key={`grid-${i}`} opacity={local * 0.9}>
            {/* horizontal */}
            <line
              x1={PX0}
              y1={toY(f)}
              x2={PX1}
              y2={toY(f)}
              stroke={CHALK.faint}
              strokeWidth="1"
              strokeDasharray="3,5"
            />
            {/* vertical */}
            <line
              x1={toX(f)}
              y1={PY0}
              x2={toX(f)}
              y2={PY1}
              stroke={CHALK.faint}
              strokeWidth="1"
              strokeDasharray="3,5"
            />
          </g>
        );
      })}

      {/* Y axis — draws bottom→top */}
      <line
        x1={PX0}
        y1={PY1}
        x2={PX0}
        y2={PY0}
        stroke={CHALK.white}
        strokeWidth="3"
        strokeLinecap="round"
        filter="url(#chalk)"
        {...chalkStroke(PLOT_H, axisLocal)}
      />
      {/* X axis — draws left→right */}
      <line
        x1={PX0}
        y1={PY1}
        x2={PX1}
        y2={PY1}
        stroke={CHALK.white}
        strokeWidth="3"
        strokeLinecap="round"
        filter="url(#chalk)"
        {...chalkStroke(PLOT_W, axisLocal)}
      />

      {/* Arrowheads on both axes */}
      <polygon
        points={`${PX1},${PY1} ${PX1 - 14},${PY1 - 7} ${PX1 - 14},${PY1 + 7}`}
        fill={CHALK.white}
        opacity={revealWindow(progress, 0.18, 0.24)}
      />
      <polygon
        points={`${PX0},${PY0} ${PX0 - 7},${PY0 + 14} ${PX0 + 7},${PY0 + 14}`}
        fill={CHALK.white}
        opacity={revealWindow(progress, 0.18, 0.24)}
      />

      {/* Axis labels — fade with the axes */}
      <text
        x={PX1}
        y={PY1 + 34}
        textAnchor="end"
        fill="rgba(255,255,255,.7)"
        fontSize="18"
        fontFamily="Bricolage Grotesque, serif"
        fontStyle="italic"
        opacity={revealWindow(progress, 0.1, 0.24)}
      >
        {xLabel}
      </text>
      <text
        x={PX0 - 18}
        y={PY0 - 4}
        textAnchor="middle"
        fill="rgba(255,255,255,.7)"
        fontSize="18"
        fontFamily="Bricolage Grotesque, serif"
        fontStyle="italic"
        opacity={revealWindow(progress, 0.1, 0.24)}
        transform={`rotate(-90 ${PX0 - 18} ${PY0 - 4})`}
      >
        {yLabel}
      </text>

      {/* Origin label */}
      <text
        x={PX0 - 14}
        y={PY1 + 22}
        textAnchor="middle"
        fill="rgba(255,255,255,.45)"
        fontSize="13"
        fontFamily="DM Sans, sans-serif"
        opacity={revealWindow(progress, 0.14, 0.26)}
      >
        0
      </text>

      {/* The curve — draws on left→right over [.3,.82] */}
      <path
        d={curvePath}
        fill="none"
        stroke={CHALK.yellow}
        strokeWidth="3.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        filter="url(#chalk)"
        {...chalkStroke(curveLen, curveLocal)}
      />

      {/* Marked points — appear in sequence over [.82, 1] */}
      {points.map((p, i) => {
        const n = Math.max(1, points.length);
        const seg = 0.18 / n;
        const slot = 0.82 + i * seg;
        const local = revealWindow(progress, slot, slot + seg * 0.9);
        if (local <= 0) return null;
        const cx = toX(p.x);
        const cy = toY(p.y);
        return (
          <g key={i} opacity={local}>
            {/* dashed connectors to the axes */}
            <line
              x1={cx}
              y1={cy}
              x2={cx}
              y2={PY1}
              stroke="rgba(245,224,103,.35)"
              strokeWidth="1.5"
              strokeDasharray="4,4"
            />
            <line
              x1={cx}
              y1={cy}
              x2={PX0}
              y2={cy}
              stroke="rgba(245,224,103,.35)"
              strokeWidth="1.5"
              strokeDasharray="4,4"
            />
            <circle
              cx={cx}
              cy={cy}
              r={6 * local}
              fill={CHALK.pink}
              filter="url(#chalk)"
            />
            <text
              x={cx}
              y={cy - 16}
              textAnchor="middle"
              fill={CHALK.pink}
              fontSize="18"
              fontFamily="Bricolage Grotesque, serif"
              fontStyle="italic"
              filter="url(#chalk)"
            >
              {p.label}
            </text>
          </g>
        );
      })}
    </g>
  );
};
