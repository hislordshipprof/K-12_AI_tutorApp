/**
 * VectorArrowsScene — one or more vectors from a common origin, optionally
 * decomposed into x/y components. Follows the scene contract in `types.ts`;
 * matches NumberLineScene's style.
 *
 * params:
 *   title?:          string                              — caption above
 *   origin?:         { x: number, y: number }            (default {300,360})
 *   vectors?:        { label: string, dx: number, dy: number,
 *                      color?: 'blue'|'yellow'|'pink'|'green' }[]
 *   showComponents?: boolean (default true)               — dashed x/y lines
 *
 * dx/dy are viewBox px; +dy is downward (SVG), so a physics "up" vector has
 * negative dy. Default (empty params): one blue vector dx=180, dy=-120, "v".
 *
 * Drawing timeline:
 *   [0,    .2]   origin dot + faint axes draw on
 *   [.2,   .75]  each vector draws on from the origin, in sequence
 *   [.75, 1.0]   dashed x/y component lines + labels (if enabled)
 */
import {
  CHALK,
  chalkStroke,
  numParam,
  revealWindow,
  strParam,
  type SceneComponent,
} from './types';

const COLORS: Record<string, string> = {
  blue: CHALK.blue,
  yellow: CHALK.yellow,
  pink: CHALK.pink,
  green: CHALK.green,
};

interface Vector {
  label: string;
  dx: number;
  dy: number;
  color?: string;
}

export const VectorArrowsScene: SceneComponent = ({ progress, params }) => {
  const title = strParam(params, 'title', '');
  const showComponents = params.showComponents !== false;

  // origin — guard the nested object
  const originRaw =
    params.origin && typeof params.origin === 'object'
      ? (params.origin as Record<string, unknown>)
      : {};
  const ox = numParam(originRaw, 'x', 300);
  const oy = numParam(originRaw, 'y', 360);

  // vectors — coerce each entry, fall back to a single default vector
  const rawVectors = Array.isArray(params.vectors) ? params.vectors : [];
  let vectors: Vector[] = rawVectors
    .filter((v): v is Record<string, unknown> => !!v && typeof v === 'object')
    .map((v) => ({
      label: typeof v.label === 'string' ? v.label : '',
      dx: typeof v.dx === 'number' && Number.isFinite(v.dx) ? v.dx : 0,
      dy: typeof v.dy === 'number' && Number.isFinite(v.dy) ? v.dy : 0,
      color: typeof v.color === 'string' ? v.color : undefined,
    }))
    .filter((v) => v.dx !== 0 || v.dy !== 0)
    .slice(0, 4);
  if (vectors.length === 0) {
    vectors = [{ label: 'v', dx: 180, dy: -120, color: 'blue' }];
  }

  const axesLocal = revealWindow(progress, 0, 0.2);
  // axes span generously around the origin within the 900×530 board
  const axMin = 60;
  const axMaxX = 840;
  const axMinY = 60;
  const axMaxY = 470;

  // window split among vectors over [.2, .75]
  const vecStart = 0.2;
  const vecEnd = 0.75;
  const vecSpan = (vecEnd - vecStart) / vectors.length;

  return (
    <g>
      {/* Title */}
      {title ? (
        <text
          x="450"
          y="58"
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

      {/* Faint axes through the origin */}
      <g opacity={axesLocal}>
        <line
          x1={axMin}
          y1={oy}
          x2={axMaxX}
          y2={oy}
          stroke={CHALK.faint}
          strokeWidth="1.5"
          strokeDasharray="5,5"
        />
        <line
          x1={ox}
          y1={axMinY}
          x2={ox}
          y2={axMaxY}
          stroke={CHALK.faint}
          strokeWidth="1.5"
          strokeDasharray="5,5"
        />
      </g>

      {/* Origin dot */}
      <circle
        cx={ox}
        cy={oy}
        r={5 * axesLocal}
        fill={CHALK.white}
        filter="url(#chalk)"
      />
      <text
        x={ox - 12}
        y={oy + 22}
        textAnchor="end"
        fill="rgba(255,255,255,.55)"
        fontSize="14"
        fontFamily="DM Sans, sans-serif"
        opacity={revealWindow(progress, 0.12, 0.2)}
      >
        O
      </text>

      {/* Vectors — each draws on from the origin in sequence */}
      {vectors.map((v, i) => {
        const color = COLORS[v.color ?? ''] ?? CHALK.blue;
        const slot0 = vecStart + i * vecSpan;
        const slot1 = slot0 + vecSpan;
        const local = revealWindow(progress, slot0, slot1);
        if (local <= 0) return null;

        const tx = ox + v.dx;
        const ty = oy + v.dy;
        const len = Math.hypot(v.dx, v.dy) || 1;
        const ux = v.dx / len;
        const uy = v.dy / len;
        // perpendicular for the arrowhead wings
        const px = -uy;
        const py = ux;
        // arrowhead opacity arrives in the last fifth of this vector's window
        const headLocal = revealWindow(
          progress,
          slot1 - vecSpan * 0.2,
          slot1,
        );

        // component reveal — over the shared [.75, 1] tail
        const compLocal = revealWindow(progress, 0.75, 1);

        return (
          <g key={i}>
            {/* x/y component dashed lines */}
            {showComponents && compLocal > 0 ? (
              <g opacity={compLocal}>
                {/* horizontal component */}
                <line
                  x1={ox}
                  y1={oy}
                  x2={tx}
                  y2={oy}
                  stroke={color}
                  strokeWidth="2"
                  strokeDasharray="6,5"
                  opacity={0.55}
                  filter="url(#chalk)"
                />
                {/* vertical component */}
                <line
                  x1={tx}
                  y1={oy}
                  x2={tx}
                  y2={ty}
                  stroke={color}
                  strokeWidth="2"
                  strokeDasharray="6,5"
                  opacity={0.55}
                  filter="url(#chalk)"
                />
                <text
                  x={(ox + tx) / 2}
                  y={oy + (v.dy < 0 ? 20 : -10)}
                  textAnchor="middle"
                  fill={color}
                  fontSize="15"
                  fontFamily="DM Sans, sans-serif"
                  opacity={0.85}
                >
                  {v.label || 'v'}
                  <tspan baselineShift="sub" fontSize="11">
                    x
                  </tspan>
                </text>
                <text
                  x={tx + (v.dx < 0 ? -10 : 12)}
                  y={(oy + ty) / 2 + 5}
                  textAnchor={v.dx < 0 ? 'end' : 'start'}
                  fill={color}
                  fontSize="15"
                  fontFamily="DM Sans, sans-serif"
                  opacity={0.85}
                >
                  {v.label || 'v'}
                  <tspan baselineShift="sub" fontSize="11">
                    y
                  </tspan>
                </text>
              </g>
            ) : null}

            {/* vector shaft */}
            <line
              x1={ox}
              y1={oy}
              x2={tx}
              y2={ty}
              stroke={color}
              strokeWidth="3.5"
              strokeLinecap="round"
              filter="url(#chalk)"
              {...chalkStroke(len, local)}
            />
            {/* arrowhead at the tip */}
            <polygon
              points={`${tx},${ty} ${tx - ux * 17 + px * 8.5},${ty - uy * 17 + py * 8.5} ${tx - ux * 17 - px * 8.5},${ty - uy * 17 - py * 8.5}`}
              fill={color}
              opacity={headLocal}
            />
            {/* label near the tip */}
            {v.label ? (
              <text
                x={tx + ux * 22}
                y={ty + uy * 22 + 6}
                textAnchor="middle"
                fill={color}
                fontSize="22"
                fontFamily="Bricolage Grotesque, serif"
                fontStyle="italic"
                filter="url(#chalk)"
                opacity={headLocal}
              >
                {v.label}
              </text>
            ) : null}
          </g>
        );
      })}
    </g>
  );
};
