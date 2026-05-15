/**
 * FreeBodyDiagramScene — a box (the object) at the centre with force arrows
 * radiating outward, each labelled. A classic free-body diagram.
 *
 * params:
 *   title?:       string                       — caption above the diagram
 *   objectLabel?: string  (default "object")    — label inside the box
 *   forces?:      { dir, label, color?, magnitude? }[]
 *     dir:        'up'|'down'|'left'|'right'|'up-left'|'up-right'
 *                 |'down-left'|'down-right'
 *     color:      'blue'|'yellow'|'pink'|'green'
 *     magnitude:  number  (default 1) — scales arrow length (base ~110px)
 *
 * Drawing timeline:
 *   [0,   .12]  title fades in
 *   [0,   .22]  box draws on
 *   [.22, 1.0]  force arrows appear in sequence — each draws from the box
 *               edge outward, then its label fades in
 */
import {
  CHALK,
  chalkStroke,
  revealWindow,
  strParam,
  type SceneComponent,
} from './types';

const CX = 450; // centre of the diagram
const CY = 285;
const BOX = 86; // box side length
const HALF = BOX / 2;
const BASE_LEN = 110; // base arrow length at magnitude 1

const COLORS: Record<string, string> = {
  blue: CHALK.blue,
  yellow: CHALK.yellow,
  pink: CHALK.pink,
  green: CHALK.green,
};

/** Unit vector for each of the 8 supported directions (SVG y points down). */
const DIRS: Record<string, { x: number; y: number }> = {
  up: { x: 0, y: -1 },
  down: { x: 0, y: 1 },
  left: { x: -1, y: 0 },
  right: { x: 1, y: 0 },
  'up-left': { x: -0.7071, y: -0.7071 },
  'up-right': { x: 0.7071, y: -0.7071 },
  'down-left': { x: -0.7071, y: 0.7071 },
  'down-right': { x: 0.7071, y: 0.7071 },
};

interface Force {
  dir: string;
  label: string;
  color?: string;
  magnitude?: number;
}

const DEFAULT_FORCES: Force[] = [
  { dir: 'down', label: 'gravity', color: 'pink' },
  { dir: 'up', label: 'normal', color: 'blue' },
];

export const FreeBodyDiagramScene: SceneComponent = ({ progress, params }) => {
  const title = strParam(params, 'title', '');
  const objectLabel = strParam(params, 'objectLabel', 'object');

  const rawForces = Array.isArray(params.forces) ? params.forces : null;
  const forces: Force[] = (rawForces ?? DEFAULT_FORCES)
    .filter(
      (f): f is Force =>
        !!f &&
        typeof f === 'object' &&
        typeof (f as Force).dir === 'string' &&
        (f as Force).dir in DIRS,
    )
    .slice(0, 8);

  // The box edge is a square; the start point of an arrow is where the
  // direction ray exits the box. For diagonal dirs we clamp to the corner-ish
  // edge by scaling against the larger axis component.
  const boxEdge = (u: { x: number; y: number }) => {
    const ax = Math.abs(u.x);
    const ay = Math.abs(u.y);
    const t = HALF / Math.max(ax, ay, 0.0001);
    return { x: CX + u.x * t, y: CY + u.y * t };
  };

  return (
    <g>
      {/* Title */}
      {title ? (
        <text
          x="450"
          y="92"
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

      {/* The object — a square box that draws on as a stroked path */}
      {(() => {
        const perim = BOX * 4;
        const d =
          `M ${CX - HALF} ${CY - HALF} ` +
          `H ${CX + HALF} V ${CY + HALF} ` +
          `H ${CX - HALF} Z`;
        return (
          <path
            d={d}
            fill="rgba(255,255,255,.05)"
            stroke={CHALK.white}
            strokeWidth="3"
            strokeLinejoin="round"
            filter="url(#chalk)"
            {...chalkStroke(perim, revealWindow(progress, 0, 0.22))}
          />
        );
      })()}

      {/* Object label inside the box */}
      <text
        x={CX}
        y={CY + 6}
        textAnchor="middle"
        fill={CHALK.white}
        fontSize="18"
        fontFamily="Bricolage Grotesque, serif"
        fontStyle="italic"
        filter="url(#chalk)"
        opacity={revealWindow(progress, 0.14, 0.24)}
      >
        {objectLabel}
      </text>

      {/* Force arrows — sequential over [.22, 1] */}
      {forces.map((f, i) => {
        const n = Math.max(1, forces.length);
        const span = 0.78 / n;
        const slot = 0.22 + i * span;
        const drawLocal = revealWindow(progress, slot, slot + span * 0.62);
        const labelLocal = revealWindow(
          progress,
          slot + span * 0.55,
          slot + span * 0.95,
        );

        const u = DIRS[f.dir] ?? { x: 0, y: -1 };
        const color = COLORS[f.color ?? ''] ?? CHALK.yellow;
        const mag = Math.max(0.3, Math.min(2.4, f.magnitude ?? 1));
        const len = BASE_LEN * mag;

        const start = boxEdge(u);
        const endX = start.x + u.x * len;
        const endY = start.y + u.y * len;
        // Animated tip rides outward as the arrow draws on.
        const tipX = start.x + u.x * len * drawLocal;
        const tipY = start.y + u.y * len * drawLocal;

        // Arrowhead: two barbs swept back from the tip.
        const headLen = 15;
        const headW = 7;
        const px = -u.y; // perpendicular
        const py = u.x;
        const baseX = tipX - u.x * headLen;
        const baseY = tipY - u.y * headLen;
        const headPts =
          `${tipX},${tipY} ` +
          `${baseX + px * headW},${baseY + py * headW} ` +
          `${baseX - px * headW},${baseY - py * headW}`;

        // Label sits just beyond the arrow tip.
        const labelX = endX + u.x * 26;
        const labelY = endY + u.y * 26 + 5;

        return (
          <g key={i}>
            <line
              x1={start.x}
              y1={start.y}
              x2={tipX}
              y2={tipY}
              stroke={color}
              strokeWidth="3.5"
              strokeLinecap="round"
              filter="url(#chalk)"
            />
            <polygon
              points={headPts}
              fill={color}
              opacity={drawLocal > 0.82 ? 1 : 0}
              filter="url(#chalk)"
            />
            <text
              x={labelX}
              y={labelY}
              textAnchor="middle"
              fill={color}
              fontSize="20"
              fontFamily="Bricolage Grotesque, serif"
              fontStyle="italic"
              filter="url(#chalk)"
              opacity={labelLocal}
            >
              {f.label}
            </text>
          </g>
        );
      })}
    </g>
  );
};
