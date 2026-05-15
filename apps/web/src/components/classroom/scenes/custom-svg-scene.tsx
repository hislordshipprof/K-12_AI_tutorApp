/**
 * CustomSvgScene — the Phase C fallback for lesson steps that don't fit any
 * of the 12 typed scenes (a biology cell, a chemistry apparatus, etc.).
 *
 * It does NOT render a model-authored SVG *string* — that would be an
 * injection surface. Instead the step carries a structured, pre-validated
 * list of drawing primitives, and this component renders each one as a real
 * React SVG element drawn from a fixed whitelist. No `dangerouslySetInnerHTML`,
 * no arbitrary attributes — every field is coerced here.
 *
 * params:
 *   title?:    string                    — caption above the drawing
 *   elements?: PrimitiveSpec[]            — the drawing, in back-to-front order
 *
 * Each primitive (see PrimitiveSpec) is one of: line, polyline, path, rect,
 * circle, ellipse, polygon, text. Elements reveal in array order across the
 * audio clock: outline shapes "draw on" (stroke-dash), filled shapes and text
 * fade in.
 */
import { CHALK, revealWindow, type SceneComponent } from './types';

const COLORS: Record<string, string> = {
  white: CHALK.white,
  blue: CHALK.blue,
  yellow: CHALK.yellow,
  pink: CHALK.pink,
  green: CHALK.green,
};

/** Resolve a palette key → chalk colour; anything unknown → white. */
function color(key: unknown): string {
  return (typeof key === 'string' ? COLORS[key] : undefined) ?? CHALK.white;
}

/** A finite number within [lo, hi], else fallback. */
function num(v: unknown, fallback: number, lo = -2000, hi = 4000): number {
  if (typeof v !== 'number' || !Number.isFinite(v)) return fallback;
  return Math.max(lo, Math.min(hi, v));
}

/** A string no longer than `max`, else ''. */
function str(v: unknown, max = 240): string {
  return typeof v === 'string' ? v.slice(0, max) : '';
}

type Rec = Record<string, unknown>;

export const CustomSvgScene: SceneComponent = ({ progress, params }) => {
  const title = str(params.title, 80);
  const raw = Array.isArray(params.elements) ? params.elements : [];
  const elements: Rec[] = raw
    .filter((e): e is Rec => !!e && typeof e === 'object')
    .slice(0, 40);

  // Title over [0, .1]; the drawing sequences across [.1, 1].
  const n = Math.max(1, elements.length);
  const span = 0.9 / n;

  return (
    <g>
      {title ? (
        <text
          x="450"
          y="150"
          textAnchor="middle"
          fill={CHALK.white}
          fontSize="26"
          fontFamily="Bricolage Grotesque, serif"
          fontStyle="italic"
          filter="url(#chalk)"
          opacity={revealWindow(progress, 0, 0.1)}
        >
          {title}
        </text>
      ) : null}

      {elements.map((e, i) => {
        const start = 0.1 + i * span;
        const local = revealWindow(progress, start, start + span * 1.1);
        if (local <= 0) return null;

        const stroke = color(e.stroke ?? 'white');
        const strokeWidth = num(e.strokeWidth, 3, 0.5, 12);
        const hasFill =
          typeof e.fill === 'string' && e.fill !== 'none' && e.fill in COLORS;
        const fill = hasFill ? color(e.fill) : 'none';
        const dashed = e.dash === true;

        // Outline primitives "draw on" via a normalised stroke-dash; filled
        // shapes and text just fade in. pathLength=1 lets us animate any
        // path/line without measuring its true geometric length.
        const drawOn = !hasFill;
        const drawProps = drawOn
          ? {
              pathLength: 1,
              strokeDasharray: dashed ? '0.04 0.03' : 1,
              strokeDashoffset: dashed ? 0 : 1 - local,
            }
          : { strokeDasharray: dashed ? '6 5' : undefined };
        const opacity = drawOn ? 1 : local;

        const common = {
          stroke,
          strokeWidth,
          fill,
          opacity,
          filter: 'url(#chalk)',
          strokeLinecap: 'round' as const,
          strokeLinejoin: 'round' as const,
        };

        switch (str(e.el, 16)) {
          case 'line':
            return (
              <line
                key={i}
                x1={num(e.x1, 0)}
                y1={num(e.y1, 0)}
                x2={num(e.x2, 0)}
                y2={num(e.y2, 0)}
                {...common}
                {...drawProps}
              />
            );
          case 'rect':
            return (
              <rect
                key={i}
                x={num(e.x, 0)}
                y={num(e.y, 0)}
                width={num(e.width, 0, 0)}
                height={num(e.height, 0, 0)}
                rx={num(e.rx, 0, 0)}
                {...common}
                {...drawProps}
              />
            );
          case 'circle':
            return (
              <circle
                key={i}
                cx={num(e.cx, 0)}
                cy={num(e.cy, 0)}
                r={num(e.r, 0, 0)}
                {...common}
                {...drawProps}
              />
            );
          case 'ellipse':
            return (
              <ellipse
                key={i}
                cx={num(e.cx, 0)}
                cy={num(e.cy, 0)}
                rx={num(e.rx, 0, 0)}
                ry={num(e.ry, 0, 0)}
                {...common}
                {...drawProps}
              />
            );
          case 'path':
            return (
              <path
                key={i}
                d={str(e.d, 2000)}
                {...common}
                {...drawProps}
              />
            );
          case 'polyline':
            return (
              <polyline
                key={i}
                points={str(e.points, 2000)}
                {...common}
                {...drawProps}
              />
            );
          case 'polygon':
            return (
              <polygon
                key={i}
                points={str(e.points, 2000)}
                {...common}
                {...drawProps}
              />
            );
          case 'text':
            return (
              <text
                key={i}
                x={num(e.x, 0)}
                y={num(e.y, 0)}
                textAnchor="middle"
                fill={stroke}
                fontSize={num(e.fontSize, 18, 8, 48)}
                fontFamily="Bricolage Grotesque, serif"
                fontStyle="italic"
                filter="url(#chalk)"
                opacity={local}
              >
                {str(e.text, 120)}
              </text>
            );
          default:
            return null;
        }
      })}
    </g>
  );
};
