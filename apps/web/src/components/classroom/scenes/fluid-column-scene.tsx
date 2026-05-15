/**
 * FluidColumnScene — an open-top container of fluid showing how pressure
 * grows with depth. The fluid fills from the bottom up; dashed depth
 * markers and inward "pressure" arrows appear in sequence.
 *
 * params:
 *   title?:             string
 *   fluidLabel?:        string  (default 'water')
 *   depthMarkers?:      { label:string; depth:number }[]  — depth 0→1
 *   showPressureArrows?: boolean (default true)
 *
 * Drawing timeline:
 *   [0,   .30]  container (3 walls, open top) draws on
 *   [.30, .60]  fluid fill rises from the bottom to the surface
 *   [.55, .85]  depth markers (dashed line + label) appear sequentially
 *   [.70, 1.0]  inward pressure arrows — longer the deeper they are
 */
import {
  chalkStroke,
  CHALK,
  revealWindow,
  strParam,
  type SceneComponent,
} from './types';

const X0 = 330; // container left wall
const X1 = 570; // container right wall
const Y_TOP = 120; // open top (fluid surface)
const Y_BOT = 440; // container floor
const W = X1 - X0;
const H = Y_BOT - Y_TOP;

interface DepthMarker {
  label: string;
  depth: number;
}

const DEFAULT_MARKERS: DepthMarker[] = [
  { label: 'shallow', depth: 0.25 },
  { label: 'deep', depth: 0.75 },
];

export const FluidColumnScene: SceneComponent = ({ progress, params }) => {
  const title = strParam(params, 'title', '');
  const fluidLabel = strParam(params, 'fluidLabel', 'water');
  const showArrows =
    typeof params.showPressureArrows === 'boolean'
      ? params.showPressureArrows
      : true;

  const rawMarkers = Array.isArray(params.depthMarkers)
    ? params.depthMarkers
    : [];
  let markers: DepthMarker[] = rawMarkers
    .filter((m): m is DepthMarker => !!m && typeof m === 'object')
    .map((m) => ({
      label: typeof m.label === 'string' ? m.label : '',
      depth:
        typeof m.depth === 'number' && Number.isFinite(m.depth)
          ? Math.max(0, Math.min(1, m.depth))
          : 0.5,
    }))
    .slice(0, 5);
  if (markers.length === 0) markers = DEFAULT_MARKERS;

  // Container walls drawn as a single open-top path: down-left, across, up-right.
  const wallPath = `M ${X0} ${Y_TOP} L ${X0} ${Y_BOT} L ${X1} ${Y_BOT} L ${X1} ${Y_TOP}`;
  const wallLen = H + W + H;
  const wallLocal = revealWindow(progress, 0, 0.3);

  // Fluid fill rises from the floor up to the surface over [.30, .60].
  const fillLocal = revealWindow(progress, 0.3, 0.6);
  const fillH = H * fillLocal;
  const fillY = Y_BOT - fillH;

  // Pressure-arrow depths: a few evenly spaced sample points.
  const arrowDepths = [0.2, 0.45, 0.7, 0.95];

  return (
    <g>
      {/* Title */}
      {title ? (
        <text
          x="450"
          y="76"
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

      {/* Fluid fill — rises from the bottom (drawn under the walls) */}
      <rect
        x={X0 + 2}
        y={fillY}
        width={W - 4}
        height={fillH}
        fill={CHALK.blue}
        fillOpacity={0.28}
        opacity={fillLocal > 0 ? 1 : 0}
      />
      {/* Surface line */}
      <line
        x1={X0 + 2}
        y1={fillY}
        x2={X1 - 2}
        y2={fillY}
        stroke={CHALK.blue}
        strokeWidth="2.5"
        strokeLinecap="round"
        filter="url(#chalk)"
        opacity={fillLocal > 0 ? 1 : 0}
      />
      {/* Fluid label, centred in the body of the fluid */}
      <text
        x={(X0 + X1) / 2}
        y={Y_BOT - 30}
        textAnchor="middle"
        fill={CHALK.blue}
        fontSize="20"
        fontFamily="Bricolage Grotesque, serif"
        fontStyle="italic"
        filter="url(#chalk)"
        opacity={revealWindow(progress, 0.52, 0.62)}
      >
        {fluidLabel}
      </text>

      {/* Container walls — open-top, draw on */}
      <path
        d={wallPath}
        fill="none"
        stroke={CHALK.white}
        strokeWidth="3.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        filter="url(#chalk)"
        {...chalkStroke(wallLen, wallLocal)}
      />

      {/* Depth markers — dashed line + label, sequentially over [.55, .85] */}
      {markers.map((m, i) => {
        const slot = 0.55 + (i / markers.length) * 0.3;
        const local = revealWindow(progress, slot, slot + 0.1);
        const my = Y_TOP + m.depth * H;
        return (
          <g key={i} opacity={local}>
            <line
              x1={X0}
              y1={my}
              x2={X1}
              y2={my}
              stroke={CHALK.yellow}
              strokeWidth="2"
              strokeDasharray="6,6"
              filter="url(#chalk)"
            />
            <text
              x={X1 + 16}
              y={my + 5}
              fill={CHALK.yellow}
              fontSize="17"
              fontFamily="Bricolage Grotesque, serif"
              fontStyle="italic"
              filter="url(#chalk)"
            >
              {m.label}
            </text>
            <text
              x={X1 + 16}
              y={my + 24}
              fill="rgba(255,255,255,.55)"
              fontSize="13"
              fontFamily="DM Sans, sans-serif"
            >
              depth {Math.round(m.depth * 100)}%
            </text>
          </g>
        );
      })}

      {/* Pressure arrows — point INTO the walls, longer the deeper. [.70,1] */}
      {showArrows
        ? arrowDepths.map((d, i) => {
            const slot = 0.7 + (i / arrowDepths.length) * 0.3;
            const local = revealWindow(progress, slot, slot + 0.12);
            const ay = Y_TOP + d * H;
            // pressure ∝ depth → arrow length grows with depth
            const fullLen = 26 + d * 64;
            const len = fullLen * local;
            // left wall: arrow points right (into wall is leftward → tip at wall)
            const leftTip = X0;
            const leftStart = X0 - len;
            const rightTip = X1;
            const rightStart = X1 + len;
            return (
              <g key={`p${i}`} opacity={local > 0 ? 1 : 0}>
                {/* left-side arrow pointing right into the wall */}
                <line
                  x1={leftStart}
                  y1={ay}
                  x2={leftTip}
                  y2={ay}
                  stroke={CHALK.pink}
                  strokeWidth="2.5"
                  strokeLinecap="round"
                  filter="url(#chalk)"
                />
                <polygon
                  points={`${leftTip},${ay} ${leftTip - 11},${ay - 6} ${leftTip - 11},${ay + 6}`}
                  fill={CHALK.pink}
                />
                {/* right-side arrow pointing left into the wall */}
                <line
                  x1={rightStart}
                  y1={ay}
                  x2={rightTip}
                  y2={ay}
                  stroke={CHALK.pink}
                  strokeWidth="2.5"
                  strokeLinecap="round"
                  filter="url(#chalk)"
                />
                <polygon
                  points={`${rightTip},${ay} ${rightTip + 11},${ay - 6} ${rightTip + 11},${ay + 6}`}
                  fill={CHALK.pink}
                />
              </g>
            );
          })
        : null}

      {/* "pressure increases with depth" annotation */}
      {showArrows ? (
        <text
          x={(X0 + X1) / 2}
          y={Y_BOT + 46}
          textAnchor="middle"
          fill="rgba(255,255,255,.6)"
          fontSize="14"
          fontFamily="DM Sans, sans-serif"
          opacity={revealWindow(progress, 0.9, 1)}
        >
          pressure increases with depth
        </text>
      ) : null}
    </g>
  );
};
