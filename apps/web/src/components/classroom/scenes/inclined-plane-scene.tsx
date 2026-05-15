/**
 * InclinedPlaneScene — a block resting on a ramp, with the standard force
 * vectors of an inclined-plane problem drawn on in sequence.
 *
 * params:
 *   title?:      string
 *   angleDeg?:   number  (default 30) — incline angle at the base
 *   blockLabel?: string  (default "block")
 *   forces?:     ('gravity'|'normal'|'friction'|'applied')[]
 *                default ['gravity','normal','friction']
 *
 * Drawing timeline:
 *   [0,   .28]  ramp (right triangle) draws on
 *   [.28, .42]  block appears on the incline
 *   [.42, 1.0]  force arrows appear in sequence + the base-angle arc
 */
import {
  CHALK,
  chalkStroke,
  numParam,
  revealWindow,
  strParam,
  type SceneComponent,
} from './types';

// Right-triangle ramp: right angle at bottom-right corner.
const BASE_X0 = 150; // bottom-left
const BASE_X1 = 760; // bottom-right (right angle here)
const BASE_Y = 420; // ground level

type ForceKind = 'gravity' | 'normal' | 'friction' | 'applied';
const VALID: ForceKind[] = ['gravity', 'normal', 'friction', 'applied'];

interface ForceDef {
  color: string;
  label: string;
}
const FORCE_META: Record<ForceKind, ForceDef> = {
  gravity: { color: CHALK.pink, label: 'gravity' },
  normal: { color: CHALK.blue, label: 'normal' },
  friction: { color: CHALK.yellow, label: 'friction' },
  applied: { color: CHALK.green, label: 'applied' },
};

export const InclinedPlaneScene: SceneComponent = ({ progress, params }) => {
  const title = strParam(params, 'title', '');
  const blockLabel = strParam(params, 'blockLabel', 'block');
  const angleDeg = Math.max(10, Math.min(55, numParam(params, 'angleDeg', 30)));
  const angle = (angleDeg * Math.PI) / 180;

  const rawForces = Array.isArray(params.forces) ? params.forces : null;
  const forces: ForceKind[] = (rawForces ?? ['gravity', 'normal', 'friction'])
    .filter((f): f is ForceKind => typeof f === 'string' && VALID.includes(f as ForceKind))
    .slice(0, 4);

  // Triangle apex: vertical edge rises from BASE_X1, hypotenuse goes
  // bottom-left → apex. Apex height = base * tan(angle).
  const baseLen = BASE_X1 - BASE_X0;
  const apexY = BASE_Y - baseLen * Math.tan(angle);
  const apexX = BASE_X1;

  // Up-slope unit vector (pointing from base-left toward the apex).
  const slopeDx = apexX - BASE_X0;
  const slopeDy = apexY - BASE_Y;
  const slopeMag = Math.hypot(slopeDx, slopeDy);
  const ux = slopeDx / slopeMag; // along incline, up-slope
  const uy = slopeDy / slopeMag;
  // Outward normal to the surface (points up-away from the ramp).
  const nx = uy;
  const ny = -ux;

  // Block sits ~62% up the incline.
  const t = 0.6;
  const surfX = BASE_X0 + slopeDx * t;
  const surfY = BASE_Y + slopeDy * t;
  const blockSize = 64;
  const blockHalf = blockSize / 2;
  // Block centre is offset off the surface by half its height along normal.
  const bcx = surfX + nx * blockHalf;
  const bcy = surfY + ny * blockHalf;

  // The four corners of the block, rotated to sit flush on the incline.
  const corner = (sAlong: number, sNormal: number) => ({
    x: bcx + ux * sAlong + nx * sNormal,
    y: bcy + uy * sAlong + ny * sNormal,
  });
  const c1 = corner(-blockHalf, -blockHalf);
  const c2 = corner(blockHalf, -blockHalf);
  const c3 = corner(blockHalf, blockHalf);
  const c4 = corner(-blockHalf, blockHalf);

  // Direction unit vectors for each force, anchored at the block centre.
  const forceVec: Record<ForceKind, { x: number; y: number }> = {
    gravity: { x: 0, y: 1 }, // straight down
    normal: { x: nx, y: ny }, // perpendicular to surface, outward
    friction: { x: ux, y: uy }, // up-slope (opposing sliding down)
    applied: { x: ux, y: uy }, // up-slope push
  };

  const ARROW_LEN = 100;

  return (
    <g>
      {/* Title */}
      {title ? (
        <text
          x="450"
          y="86"
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

      {/* Ramp — right triangle drawn as one stroked path */}
      {(() => {
        const segHyp = slopeMag;
        const segVert = BASE_Y - apexY;
        const segBase = baseLen;
        const perim = segHyp + segVert + segBase;
        const d =
          `M ${BASE_X0} ${BASE_Y} ` +
          `L ${apexX} ${apexY} ` +
          `L ${BASE_X1} ${BASE_Y} Z`;
        return (
          <path
            d={d}
            fill="rgba(255,255,255,.05)"
            stroke={CHALK.white}
            strokeWidth="3"
            strokeLinejoin="round"
            filter="url(#chalk)"
            {...chalkStroke(perim, revealWindow(progress, 0, 0.28))}
          />
        );
      })()}

      {/* Base-angle arc + label at bottom-left corner */}
      {(() => {
        const local = revealWindow(progress, 0.42, 0.56);
        if (local <= 0) return null;
        const r = 56;
        // Arc from along-the-base (toward BASE_X1) up to along the hypotenuse.
        const a0x = BASE_X0 + r;
        const a0y = BASE_Y;
        const a1x = BASE_X0 + ux * r;
        const a1y = BASE_Y + uy * r;
        return (
          <g opacity={local}>
            <path
              d={`M ${a0x} ${a0y} A ${r} ${r} 0 0 0 ${a1x} ${a1y}`}
              fill="none"
              stroke="rgba(255,255,255,.5)"
              strokeWidth="2"
              filter="url(#chalk)"
            />
            <text
              x={BASE_X0 + r + 16}
              y={BASE_Y - 14}
              fill="rgba(255,255,255,.7)"
              fontSize="16"
              fontFamily="DM Sans, sans-serif"
            >
              {Math.round(angleDeg)}°
            </text>
          </g>
        );
      })()}

      {/* The block on the incline */}
      {(() => {
        const local = revealWindow(progress, 0.28, 0.42);
        if (local <= 0) return null;
        const perim = blockSize * 4;
        const d =
          `M ${c1.x} ${c1.y} L ${c2.x} ${c2.y} ` +
          `L ${c3.x} ${c3.y} L ${c4.x} ${c4.y} Z`;
        return (
          <g>
            <path
              d={d}
              fill="rgba(168,196,232,.12)"
              stroke={CHALK.white}
              strokeWidth="3"
              strokeLinejoin="round"
              filter="url(#chalk)"
              {...chalkStroke(perim, local)}
            />
            <text
              x={bcx}
              y={bcy + 5}
              textAnchor="middle"
              fill={CHALK.white}
              fontSize="15"
              fontFamily="Bricolage Grotesque, serif"
              fontStyle="italic"
              filter="url(#chalk)"
              opacity={revealWindow(progress, 0.34, 0.44)}
            >
              {blockLabel}
            </text>
          </g>
        );
      })()}

      {/* Force arrows — sequential over [.42, 1] */}
      {forces.map((kind, i) => {
        const n = Math.max(1, forces.length);
        const segLen = 0.58 / n;
        const slot = 0.42 + i * segLen;
        const drawLocal = revealWindow(progress, slot, slot + segLen * 0.62);
        const labelLocal = revealWindow(
          progress,
          slot + segLen * 0.55,
          slot + segLen * 0.95,
        );
        if (drawLocal <= 0) return null;

        const v = forceVec[kind];
        const meta = FORCE_META[kind];
        const endX = bcx + v.x * ARROW_LEN;
        const endY = bcy + v.y * ARROW_LEN;
        const tipX = bcx + v.x * ARROW_LEN * drawLocal;
        const tipY = bcy + v.y * ARROW_LEN * drawLocal;

        const headLen = 14;
        const headW = 7;
        const px = -v.y;
        const py = v.x;
        const baseX = tipX - v.x * headLen;
        const baseY = tipY - v.y * headLen;
        const headPts =
          `${tipX},${tipY} ` +
          `${baseX + px * headW},${baseY + py * headW} ` +
          `${baseX - px * headW},${baseY - py * headW}`;

        const labelX = endX + v.x * 24;
        const labelY = endY + v.y * 24 + 5;

        return (
          <g key={kind}>
            <line
              x1={bcx}
              y1={bcy}
              x2={tipX}
              y2={tipY}
              stroke={meta.color}
              strokeWidth="3.5"
              strokeLinecap="round"
              filter="url(#chalk)"
            />
            <polygon
              points={headPts}
              fill={meta.color}
              opacity={drawLocal > 0.82 ? 1 : 0}
              filter="url(#chalk)"
            />
            <text
              x={labelX}
              y={labelY}
              textAnchor="middle"
              fill={meta.color}
              fontSize="18"
              fontFamily="Bricolage Grotesque, serif"
              fontStyle="italic"
              filter="url(#chalk)"
              opacity={labelLocal}
            >
              {meta.label}
            </text>
          </g>
        );
      })}
    </g>
  );
};
