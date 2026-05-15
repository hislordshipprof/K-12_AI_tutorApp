/**
 * SpringMassScene — a mass on a coiled spring attached to a wall, with an
 * optional equilibrium marker and displacement arrow. Follows the scene
 * contract in `types.ts`; matches NumberLineScene's style.
 *
 * params:
 *   title?:           string                          — caption above
 *   orientation?:     'horizontal' | 'vertical'        (default 'horizontal')
 *   massLabel?:       string  (default 'm')            — label on the block
 *   showEquilibrium?: boolean (default true)           — dashed marker + arrow
 *
 * Drawing timeline:
 *   [0,    .2]   wall (hatched) draws on
 *   [.2,   .5]   the coiled spring draws on
 *   [.5,   .65]  the mass block appears
 *   [.65, 1.0]   equilibrium marker + displacement arrow draw on
 */
import {
  CHALK,
  chalkStroke,
  revealWindow,
  strParam,
  type SceneComponent,
} from './types';

const COILS = 9; // number of zig-zag coils in the spring
const MASS = 110; // mass block side length

export const SpringMassScene: SceneComponent = ({ progress, params }) => {
  const title = strParam(params, 'title', '');
  const orientationRaw = strParam(params, 'orientation', 'horizontal');
  const vertical = orientationRaw === 'vertical';
  const massLabel = strParam(params, 'massLabel', 'm');
  const showEquilibrium = params.showEquilibrium !== false;

  // Geometry is computed along a 1-D "axis" then mapped to x/y so the same
  // coil maths drives both orientations.
  //  - horizontal: axis runs left→right, wall on the left
  //  - vertical:   axis runs top→bottom, wall (ceiling) on top
  const axisStart = vertical ? 110 : 150; // where the spring begins
  const axisEnd = vertical ? 350 : 540; // where the spring ends / block starts
  const cross = vertical ? 450 : 265; // the perpendicular centre line

  // map an axis coordinate (+ perpendicular offset) to viewBox x/y
  const pt = (along: number, perp: number): [number, number] =>
    vertical ? [cross + perp, along] : [along + 0, cross + perp];
  const ptX = (along: number, perp: number) => pt(along, perp)[0];
  const ptY = (along: number, perp: number) => pt(along, perp)[1];

  // ── Spring coil polyline ──────────────────────────────────────────────
  const springLen = axisEnd - axisStart;
  const lead = 26; // straight lead-in at each end
  const coilSpan = springLen - lead * 2;
  const coilAmp = 34;
  const pts: Array<[number, number]> = [];
  pts.push(pt(axisStart, 0));
  pts.push(pt(axisStart + lead, 0));
  for (let i = 0; i < COILS; i++) {
    const a0 = axisStart + lead + (coilSpan * (i + 0.25)) / COILS;
    const a1 = axisStart + lead + (coilSpan * (i + 0.75)) / COILS;
    pts.push(pt(a0, -coilAmp));
    pts.push(pt(a1, coilAmp));
  }
  pts.push(pt(axisEnd - lead, 0));
  pts.push(pt(axisEnd, 0));

  // approximate polyline length for the draw-on stroke
  let springPathLen = 0;
  for (let i = 1; i < pts.length; i++) {
    const a = pts[i];
    const b = pts[i - 1];
    if (a && b) springPathLen += Math.hypot(a[0] - b[0], a[1] - b[1]);
  }
  const springPoints = pts.map((p) => `${p[0]},${p[1]}`).join(' ');
  const springLocal = revealWindow(progress, 0.2, 0.5);

  // ── Wall (hatched) ────────────────────────────────────────────────────
  const wallLocal = revealWindow(progress, 0, 0.2);
  const wallThick = 22;
  // wall face spans the perpendicular extent of the diagram
  const wallSpan = 150;
  const wallHatches = 7;

  // ── Mass block ────────────────────────────────────────────────────────
  const massLocal = revealWindow(progress, 0.5, 0.65);
  const massCx = ptX(axisEnd + MASS / 2, 0);
  const massCy = ptY(axisEnd + MASS / 2, 0);
  const massScale = massLocal;

  // ── Equilibrium marker + displacement arrow ───────────────────────────
  const eqLocal = revealWindow(progress, 0.65, 1);
  const disp = 70; // displacement extent in px
  const arrowAlong = axisEnd + MASS / 2;

  return (
    <g>
      {/* Title */}
      {title ? (
        <text
          x="450"
          y="60"
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

      {/* Wall — a face line plus hatching */}
      <g opacity={wallLocal}>
        {vertical ? (
          <>
            <line
              x1={cross - wallSpan / 2}
              y1={axisStart}
              x2={cross + wallSpan / 2}
              y2={axisStart}
              stroke={CHALK.white}
              strokeWidth="3.5"
              strokeLinecap="round"
              filter="url(#chalk)"
            />
            {Array.from({ length: wallHatches }, (_, i) => {
              const x =
                cross - wallSpan / 2 + (wallSpan * i) / (wallHatches - 1);
              return (
                <line
                  key={i}
                  x1={x}
                  y1={axisStart}
                  x2={x - wallThick}
                  y2={axisStart - wallThick}
                  stroke="rgba(255,255,255,.5)"
                  strokeWidth="2"
                  filter="url(#chalk)"
                />
              );
            })}
          </>
        ) : (
          <>
            <line
              x1={axisStart}
              y1={cross - wallSpan / 2}
              x2={axisStart}
              y2={cross + wallSpan / 2}
              stroke={CHALK.white}
              strokeWidth="3.5"
              strokeLinecap="round"
              filter="url(#chalk)"
            />
            {Array.from({ length: wallHatches }, (_, i) => {
              const y =
                cross - wallSpan / 2 + (wallSpan * i) / (wallHatches - 1);
              return (
                <line
                  key={i}
                  x1={axisStart}
                  y1={y}
                  x2={axisStart - wallThick}
                  y2={y - wallThick}
                  stroke="rgba(255,255,255,.5)"
                  strokeWidth="2"
                  filter="url(#chalk)"
                />
              );
            })}
          </>
        )}
      </g>

      {/* Spring — coiled polyline that draws on */}
      <polyline
        points={springPoints}
        fill="none"
        stroke={CHALK.blue}
        strokeWidth="3"
        strokeLinecap="round"
        strokeLinejoin="round"
        filter="url(#chalk)"
        {...chalkStroke(springPathLen, springLocal)}
      />

      {/* Equilibrium marker + displacement arrow */}
      {showEquilibrium && eqLocal > 0 ? (
        <g>
          {/* dashed equilibrium line through the block centre */}
          {vertical ? (
            <line
              x1={massCx - MASS}
              y1={massCy}
              x2={massCx + MASS}
              y2={massCy}
              stroke="rgba(245,224,103,.55)"
              strokeWidth="2"
              strokeDasharray="6,6"
              opacity={eqLocal}
            />
          ) : (
            <line
              x1={massCx}
              y1={massCy - MASS}
              x2={massCx}
              y2={massCy + MASS}
              stroke="rgba(245,224,103,.55)"
              strokeWidth="2"
              strokeDasharray="6,6"
              opacity={eqLocal}
            />
          )}
          <text
            x={vertical ? massCx + MASS + 8 : massCx}
            y={vertical ? massCy + 5 : massCy - MASS - 10}
            textAnchor={vertical ? 'start' : 'middle'}
            fill={CHALK.yellow}
            fontSize="14"
            fontFamily="DM Sans, sans-serif"
            opacity={eqLocal}
          >
            equilibrium
          </text>

          {/* displacement double-arrow showing oscillation extent */}
          {(() => {
            const drawLocal = revealWindow(progress, 0.78, 1);
            const off = vertical ? 90 : -130; // perpendicular offset of the arrow
            const a0 = arrowAlong - disp;
            const a1 = arrowAlong + disp * drawLocal;
            const [x0, y0] = pt(a0, off);
            const [x1, y1] = pt(a1, off);
            // arrowhead direction unit vector along the axis
            const dx = vertical ? 0 : 1;
            const dy = vertical ? 1 : 0;
            return (
              <g opacity={drawLocal}>
                <line
                  x1={x0}
                  y1={y0}
                  x2={x1}
                  y2={y1}
                  stroke={CHALK.pink}
                  strokeWidth="3"
                  strokeLinecap="round"
                  filter="url(#chalk)"
                />
                {/* head at the negative end */}
                <polygon
                  points={`${x0},${y0} ${x0 + dx * 14 - dy * 7},${y0 + dy * 14 - dx * 7} ${x0 + dx * 14 + dy * 7},${y0 + dy * 14 + dx * 7}`}
                  fill={CHALK.pink}
                  opacity={revealWindow(progress, 0.96, 1)}
                />
                {/* head at the positive end */}
                <polygon
                  points={`${x1},${y1} ${x1 - dx * 14 - dy * 7},${y1 - dy * 14 - dx * 7} ${x1 - dx * 14 + dy * 7},${y1 - dy * 14 + dx * 7}`}
                  fill={CHALK.pink}
                  opacity={revealWindow(progress, 0.96, 1)}
                />
                <text
                  x={vertical ? x1 + 18 : (x0 + x1) / 2}
                  y={vertical ? (y0 + y1) / 2 + 5 : y0 - 14}
                  textAnchor="middle"
                  fill={CHALK.pink}
                  fontSize="22"
                  fontFamily="Bricolage Grotesque, serif"
                  fontStyle="italic"
                  filter="url(#chalk)"
                  opacity={revealWindow(progress, 0.92, 1)}
                >
                  x
                </text>
              </g>
            );
          })()}
        </g>
      ) : null}

      {/* Mass block — pops in, scaling from its centre */}
      {massLocal > 0 ? (
        <g
          opacity={massLocal}
          transform={`translate(${massCx} ${massCy}) scale(${massScale}) translate(${-massCx} ${-massCy})`}
        >
          <rect
            x={massCx - MASS / 2}
            y={massCy - MASS / 2}
            width={MASS}
            height={MASS}
            rx="8"
            fill="rgba(168,196,232,.16)"
            stroke={CHALK.blue}
            strokeWidth="3"
            filter="url(#chalk)"
          />
          <text
            x={massCx}
            y={massCy + 11}
            textAnchor="middle"
            fill={CHALK.white}
            fontSize="32"
            fontFamily="Bricolage Grotesque, serif"
            fontStyle="italic"
            filter="url(#chalk)"
          >
            {massLabel}
          </text>
        </g>
      ) : null}
    </g>
  );
};
