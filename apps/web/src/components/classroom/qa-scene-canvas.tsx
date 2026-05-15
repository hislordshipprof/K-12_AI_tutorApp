'use client';

import { useEffect, useRef, useState } from 'react';

import { getScene } from './scenes';

export interface QAScene {
  type: string;
  params: Record<string, unknown>;
}

interface QASceneCanvasProps {
  /** Scene to draw, or null for a text-only answer. */
  scene: QAScene | null;
}

/** ms for a scene to fully draw itself once it arrives. */
const DRAW_MS = 3600;

/**
 * Renders a follow-up answer's diagram with the SAME scene engine the
 * lesson steps use (SCENE_REGISTRY). The Q&A endpoint keyword-matches the
 * question and streams a `scene` SSE frame; this component animates it.
 *
 * Lesson steps drive scene `progress` off the TTS audio clock — a Q&A
 * answer has no such clock, so we run a self-contained ease-out draw-on
 * that restarts whenever a new scene arrives.
 */
export function QASceneCanvas({ scene }: QASceneCanvasProps) {
  const [progress, setProgress] = useState(0);
  const rafRef = useRef<number | null>(null);

  useEffect(() => {
    if (rafRef.current) cancelAnimationFrame(rafRef.current);
    if (!scene) {
      setProgress(0);
      return;
    }
    setProgress(0);
    const start = performance.now();
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / DRAW_MS);
      // ease-out cubic — fast start, gentle settle
      setProgress(1 - Math.pow(1 - t, 3));
      if (t < 1) rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [scene]);

  if (!scene) return null;
  const SceneComponent = getScene(scene.type);
  if (!SceneComponent) return null;

  return (
    <svg
      viewBox="0 0 900 530"
      preserveAspectRatio="xMidYMid meet"
      style={{
        position: 'absolute',
        inset: 0,
        width: '100%',
        height: '100%',
        pointerEvents: 'none',
        zIndex: 1,
      }}
      aria-hidden="true"
    >
      <defs>
        {/* Same chalk/glow filters the whiteboard provides — scene
            components reference url(#chalk) / url(#glow) by fixed id. */}
        <filter id="chalk">
          <feTurbulence
            type="fractalNoise"
            baseFrequency=".65"
            numOctaves="3"
            stitchTiles="stitch"
            result="n"
          />
          <feDisplacementMap
            in="SourceGraphic"
            in2="n"
            scale="1.5"
            xChannelSelector="R"
            yChannelSelector="G"
          />
        </filter>
        <filter id="glow">
          <feGaussianBlur stdDeviation="3" result="b" />
          <feMerge>
            <feMergeNode in="b" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>
      <SceneComponent progress={progress} params={scene.params} />
    </svg>
  );
}
