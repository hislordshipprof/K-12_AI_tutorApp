/**
 * Scene registry — maps a lesson step's `scene.type` string to the React
 * component that draws it. The whiteboard looks scenes up here.
 *
 * Adding a scene: implement a `SceneComponent` in its own file, then add
 * one line to SCENE_REGISTRY below. Keep the key kebab-case — it's what
 * the lesson generator emits.
 */
import { CircularMotionScene } from './circular-motion-scene';
import { CollisionScene } from './collision-scene';
import { EnergyBarChartScene } from './energy-bar-chart-scene';
import { FluidColumnScene } from './fluid-column-scene';
import { FreeBodyDiagramScene } from './free-body-diagram-scene';
import { InclinedPlaneScene } from './inclined-plane-scene';
import { MotionGraphScene } from './motion-graph-scene';
import { NumberLineScene } from './number-line-scene';
import { ProjectileArcScene } from './projectile-arc-scene';
import { SpringMassScene } from './spring-mass-scene';
import type { SceneComponent } from './types';
import { VectorArrowsScene } from './vector-arrows-scene';
import { WaveScene } from './wave-scene';

export const SCENE_REGISTRY: Record<string, SceneComponent> = {
  'number-line': NumberLineScene,
  'free-body-diagram': FreeBodyDiagramScene,
  'projectile-arc': ProjectileArcScene,
  'inclined-plane': InclinedPlaneScene,
  'motion-graph': MotionGraphScene,
  wave: WaveScene,
  'spring-mass': SpringMassScene,
  'circular-motion': CircularMotionScene,
  'energy-bar-chart': EnergyBarChartScene,
  'vector-arrows': VectorArrowsScene,
  collision: CollisionScene,
  'fluid-column': FluidColumnScene,
};

/** Scene type keys the lesson generator is allowed to emit. */
export const SCENE_TYPES = Object.keys(SCENE_REGISTRY);

/** Look up a scene component; returns null for an unknown type. */
export function getScene(type: string | null | undefined): SceneComponent | null {
  if (!type) return null;
  return SCENE_REGISTRY[type] ?? null;
}

export type { SceneComponent, SceneProps } from './types';
