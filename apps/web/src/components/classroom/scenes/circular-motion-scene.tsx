/**
 * CircularMotionScene — an object in uniform circular motion, with optional
 * centripetal-force and velocity arrows. Follows the scene contract in
 * `types.ts`; matches NumberLineScene's style.
 *
 * params:
 *   title?:           string                  — caption above
 *   showCentripetal?: boolean (default true)   — force arrow toward centre
 *   showVelocity?:    boolean (default true)   — velocity arrow (tangent)
 *   objectLabel?:     string                   — label beside the object
 *
 * Drawing timeline:
 *   [0,    .45]  the circular path draws on
 *   [.3,   .5]   centre dot + radius line draw on
 *   [.5,   .62]  the orbiting object appears (at ~45°)
 *   [.62,  .82]  centripetal-force arrow (if enabled)
 *   [.82, 1.0]   velocity arrow (if enabled)
 */
import {
  CHALK,
  chalkStroke,
  revealWindow,
  strParam,
  type SceneComponent,
} from './types';

const CX = 450; // circle centre x
const CY = 290; // circle centre y
const R = 150; // circle radius

export const CircularMotionScene: SceneComponent = ({ progress, params }) => {
  const title = strParam(params, 'title', '');
  const showCentripetal = params.showCentripetal !== false;
  const showVelocity = params.showVelocity !== false;
  const objectLabel = strParam(params, 'objectLabel', '');

  // The object sits at 45° (up-and-right of centre). SVG y is down, so a
  // "up" position uses a negative sin term.
  const angle = -Math.PI / 4;
  const objX = CX + R * Math.cos(angle);
  const objY = CY + R * Math.sin(angle);

  const circumference = 2 * Math.PI * R;
  const circleLocal = revealWindow(progress, 0, 0.45);
  const centreLocal = revealWindow(progress, 0.3, 0.5);
  const objLocal = revealWindow(progress, 0.5, 0.62);

  // unit vector from object → centre (centripetal direction)
  const toC = { x: (CX - objX) / R, y: (CY - objY) / R };
  // tangent unit vector (counter-clockwise travel) — perpendicular to radius
  const tan = { x: toC.y, y: -toC.x };

  const ARROW = 96; // arrow shaft length in px

  return (
    <g>
      {/* Title */}
      {title ? (
        <text
          x="450"
          y="62"
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

      {/* Circular path — draws on. rotate so the stroke starts at the top. */}
      <circle
        cx={CX}
        cy={CY}
        r={R}
        fill="none"
        stroke="rgba(255,255,255,.7)"
        strokeWidth="3"
        strokeLinecap="round"
        filter="url(#chalk)"
        transform={`rotate(-90 ${CX} ${CY})`}
        {...chalkStroke(circumference, circleLocal)}
      />

      {/* Centre dot + radius line to the object */}
      <g opacity={centreLocal}>
        <circle cx={CX} cy={CY} r="5" fill={CHALK.white} filter="url(#chalk)" />
        {(() => {
          const rLocal = revealWindow(progress, 0.34, 0.5);
          return (
            <line
              x1={CX}
              y1={CY}
              x2={CX + (objX - CX) * rLocal}
              y2={CY + (objY - CY) * rLocal}
              stroke="rgba(255,255,255,.55)"
              strokeWidth="2"
              strokeDasharray="6,5"
              filter="url(#chalk)"
            />
          );
        })()}
        <text
          x={(CX + objX) / 2 + 6}
          y={(CY + objY) / 2 - 10}
          fill="rgba(255,255,255,.6)"
          fontSize="16"
          fontFamily="Bricolage Grotesque, serif"
          fontStyle="italic"
          opacity={revealWindow(progress, 0.42, 0.5)}
        >
          r
        </text>
      </g>

      {/* Orbiting object */}
      {objLocal > 0 ? (
        <g>
          <circle
            cx={objX}
            cy={objY}
            r={11 * objLocal}
            fill={CHALK.yellow}
            filter="url(#chalk)"
          />
          {objectLabel ? (
            <text
              x={objX + 20}
              y={objY - 16}
              fill={CHALK.yellow}
              fontSize="20"
              fontFamily="Bricolage Grotesque, serif"
              fontStyle="italic"
              filter="url(#chalk)"
              opacity={revealWindow(progress, 0.56, 0.62)}
            >
              {objectLabel}
            </text>
          ) : null}
        </g>
      ) : null}

      {/* Centripetal-force arrow — object → centre */}
      {showCentripetal ? (
        (() => {
          const local = revealWindow(progress, 0.62, 0.82);
          if (local <= 0) return null;
          const tipX = objX + toC.x * ARROW * local;
          const tipY = objY + toC.y * ARROW * local;
          // perpendicular for the arrowhead wings
          const px = -toC.y;
          const py = toC.x;
          return (
            <g>
              <line
                x1={objX}
                y1={objY}
                x2={tipX}
                y2={tipY}
                stroke={CHALK.pink}
                strokeWidth="3.5"
                strokeLinecap="round"
                filter="url(#chalk)"
              />
              <polygon
                points={`${tipX},${tipY} ${tipX - toC.x * 16 + px * 8},${tipY - toC.y * 16 + py * 8} ${tipX - toC.x * 16 - px * 8},${tipY - toC.y * 16 - py * 8}`}
                fill={CHALK.pink}
                opacity={revealWindow(progress, 0.78, 0.82)}
              />
              <text
                x={objX + toC.x * (ARROW + 24)}
                y={objY + toC.y * (ARROW + 24) + 6}
                textAnchor="middle"
                fill={CHALK.pink}
                fontSize="22"
                fontFamily="Bricolage Grotesque, serif"
                fontStyle="italic"
                filter="url(#chalk)"
                opacity={revealWindow(progress, 0.74, 0.82)}
              >
                F
                <tspan baselineShift="sub" fontSize="15">
                  c
                </tspan>
              </text>
            </g>
          );
        })()
      ) : null}

      {/* Velocity arrow — tangent to the circle at the object */}
      {showVelocity ? (
        (() => {
          const local = revealWindow(progress, 0.82, 1);
          if (local <= 0) return null;
          const tipX = objX + tan.x * ARROW * local;
          const tipY = objY + tan.y * ARROW * local;
          const px = -tan.y;
          const py = tan.x;
          return (
            <g>
              <line
                x1={objX}
                y1={objY}
                x2={tipX}
                y2={tipY}
                stroke={CHALK.blue}
                strokeWidth="3.5"
                strokeLinecap="round"
                filter="url(#chalk)"
              />
              <polygon
                points={`${tipX},${tipY} ${tipX - tan.x * 16 + px * 8},${tipY - tan.y * 16 + py * 8} ${tipX - tan.x * 16 - px * 8},${tipY - tan.y * 16 - py * 8}`}
                fill={CHALK.blue}
                opacity={revealWindow(progress, 0.95, 1)}
              />
              <text
                x={objX + tan.x * (ARROW + 22)}
                y={objY + tan.y * (ARROW + 22) + 6}
                textAnchor="middle"
                fill={CHALK.blue}
                fontSize="22"
                fontFamily="Bricolage Grotesque, serif"
                fontStyle="italic"
                filter="url(#chalk)"
                opacity={revealWindow(progress, 0.9, 1)}
              >
                v
              </text>
            </g>
          );
        })()
      ) : null}
    </g>
  );
};
