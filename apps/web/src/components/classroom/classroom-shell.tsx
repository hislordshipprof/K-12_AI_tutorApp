'use client';

import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';

import { AriaMascot } from '@/components/aria/aria-mascot';
import { Icon } from '@/components/aria/icon';
import { MathContent } from '@/components/aria/math-content';
import { CaptionBar } from '@/components/classroom/caption-bar';
import { PeerPresence } from '@/components/classroom/peer-presence';
import { QAOverlay } from '@/components/classroom/qa-overlay';
import { QuizMePop } from '@/components/classroom/quiz-me-pop';
import { ReactionsCluster, type Reaction } from '@/components/classroom/reactions-cluster';
import { ReplyBar } from '@/components/classroom/reply-bar';
import { SketchLayer, type SketchApi } from '@/components/classroom/sketch-layer';
import { SketchToolbar } from '@/components/classroom/sketch-toolbar';
import { VoiceBar } from '@/components/classroom/voice-bar';
import { VoiceMode } from '@/components/classroom/voice-mode';
import { WhiteboardSVG } from '@/components/classroom/whiteboard-svg';
import { useSession } from '@/hooks/use-session';
import {
  useSketchRecognition,
  type SketchStroke,
} from '@/hooks/use-sketch-recognition';
import {
  useSocraticAria,
  type RecognizedShape,
} from '@/hooks/use-socratic-aria';
import { useTtsPlayback } from '@/hooks/use-tts-playback';
import { api } from '@/lib/api';

/**
 * Step-level resume bookmark used when an overlay (Q&A, voice, sketch,
 * quiz-me) interrupts the lesson. Per `docs/interruption-architecture.md`
 * § Modality 2 — we snapshot where Aria was so we can pick up mid-sentence
 * on "Got it · Resume".
 */
interface TtsBookmark {
  stepIndex: number;
  audioOffsetMs: number;
}

interface LessonStep {
  /** Caption JSX with highlighted spans. Used when the step has no math. */
  jsx?: ReactNode;
  /**
   * Mixed HTML + LaTeX math for the caption. When set, this takes precedence
   * over `jsx` and is rendered through `<MathContent>` so $...$ / $$...$$
   * delimiters typeset via KaTeX. Future steps populated by the content
   * pipeline (B3) will use only this field.
   */
  html?: string;
  /** Plain-text fallback used for text-to-speech. */
  tts: string;
  /** Mock duration label shown in the outline. */
  dur: string;
}

const LESSON_STEPS: LessonStep[] = [
  { jsx: 'Preparing your lesson…', tts: 'Preparing your lesson.', dur: '00:00' },
  {
    jsx: (
      <>
        Every wave starts at a <span className="hl-y">rest position</span> — the line everything
        wobbles around.
      </>
    ),
    tts: 'Every wave starts at a rest position — the line everything wobbles around.',
    dur: '01:20',
  },
  {
    jsx: (
      <>
        Now I&apos;ll draw the wave. Watch how it oscillates <span className="hl-b">above</span> and{' '}
        <span className="hl-p">below</span> equilibrium.
      </>
    ),
    tts: "Now I'll draw the wave. Watch how it oscillates above and below equilibrium.",
    dur: '02:15',
  },
  {
    jsx: (
      <>
        The high points are <span className="hl-y">crests</span> and the low points are{' '}
        <span className="hl-p">troughs</span>.
      </>
    ),
    tts: 'The high points are crests, and the low points are troughs.',
    dur: '03:40',
  },
  {
    jsx: (
      <>
        The <span className="hl-p">amplitude</span> is how far the wave goes from rest — it&apos;s
        the wave&apos;s <em>energy</em>.
      </>
    ),
    tts: "The amplitude is how far the wave goes from rest. It's the wave's energy.",
    dur: '05:10',
  },
  {
    html: 'One full cycle, crest to crest, is the <span class="hl-g">wavelength</span> — that lowercase $\\lambda$.',
    tts: 'One full cycle, crest to crest, is the wavelength. That lowercase lambda.',
    dur: '07:30',
  },
  {
    jsx: (
      <>
        How often a wave repeats is <span className="hl-y">frequency</span>. Its inverse is the{' '}
        <span className="hl-y">period</span>.
      </>
    ),
    tts: 'How often a wave repeats is frequency. Its inverse is the period.',
    dur: '09:50',
  },
  {
    html: 'Put it together: <span class="hl-y">$v = f \\cdot \\lambda$</span>. Speed equals frequency times wavelength. That\'s the whole game.',
    tts: "Put it together: v equals f times lambda. Speed equals frequency times wavelength. That's the whole game.",
    dur: '12:40',
  },
];

const LESSON_AUTO_ADVANCE_MS = 8000;

const STEP_TITLES = [
  '',
  'Equilibrium',
  'Drawing the wave',
  'Crests & troughs',
  'Amplitude',
  'Wavelength (λ)',
  'Frequency & period',
  'The wave equation',
];

export interface ClassroomTopic {
  slug: string;
  unit: string;
  title: string;
}

interface ClassroomShellProps {
  topic: ClassroomTopic;
}

/**
 * Top-level classroom experience — chalkboard stage, lesson stepper,
 * sketch overlay, Socratic Aria, voice mode, Q&A, quiz interrupt,
 * reactions, and the sidebar outline.
 *
 * The bulk of this component is wiring: sequencing audio + auto-advance,
 * routing reactions / sketches / replies to the right state, and
 * suppressing playback while modals are open.
 */
export function ClassroomShell({ topic }: ClassroomShellProps) {
  const router = useRouter();
  const { sessionId } = useSession(topic.slug);

  const [step, setStep] = useState(2);
  const [playing, setPlaying] = useState(true);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [qaOpen, setQaOpen] = useState(false);
  const [qaInitialQ, setQaInitialQ] = useState<string | null>(null);
  const [voiceOpen, setVoiceOpen] = useState(false);
  const [muted, setMuted] = useState(true);
  const [reactionMsg, setReactionMsg] = useState<Reaction | null>(null);

  // Sketch state.
  const [sketchOn, setSketchOn] = useState(false);
  const [sketchColor, setSketchColor] = useState('rgba(255,255,255,.85)');
  const [sketchEraser, setSketchEraser] = useState(false);
  const [strokeCount, setStrokeCount] = useState(0);
  const [lastStrokeAt, setLastStrokeAt] = useState(0);
  const [hintsRequested, setHintsRequested] = useState(0);
  const [recognizedShape, setRecognizedShape] = useState<RecognizedShape>(null);
  const [studentReply, setStudentReply] = useState<string | null>(null);
  const sketchApi = useRef<SketchApi>({});
  const recognition = useSketchRecognition();

  // Quiz-me-now interrupt.
  const [quizMeOpen, setQuizMeOpen] = useState(false);

  const total = LESSON_STEPS.length - 1;
  const tts = useTtsPlayback({ muted, rate: 1 });
  const { speaking } = tts;
  /** Bookmark snapshot taken whenever an overlay interrupts playback. */
  const [bookmark, setBookmark] = useState<TtsBookmark | null>(null);

  /**
   * Snapshot where Aria is in the current step's narration and hard-flush
   * the playback queue. Called on every overlay open so the student can
   * later pick up mid-sentence.
   */
  const snapshotAndFlush = useCallback(() => {
    setBookmark({ stepIndex: step, audioOffsetMs: tts.getCurrentMs() });
    tts.flush();
  }, [step, tts]);

  const socraticMsg = useSocraticAria({
    active: sketchOn,
    strokeCount,
    lastStrokeAt,
    hintsRequested,
    recognizedShape,
    studentReply,
  });

  // Speak the active step's caption when conditions allow. If we have a
  // bookmark for this step (because an overlay just closed), resume from
  // the captured offset instead of restarting from the top.
  useEffect(() => {
    if (!playing || qaOpen || voiceOpen || sketchOn || quizMeOpen || reactionMsg) return;
    const s = LESSON_STEPS[step];
    if (!s) return;
    const resumeFromMs =
      bookmark && bookmark.stepIndex === step ? bookmark.audioOffsetMs : 0;
    tts.start({ text: s.tts, startMs: resumeFromMs });
    // Bookmark has been consumed — clear so subsequent step changes start fresh.
    if (resumeFromMs > 0) setBookmark(null);
    return () => tts.flush();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step, playing, qaOpen, voiceOpen, sketchOn, quizMeOpen, muted]);

  // Auto-advance through steps.
  useEffect(() => {
    if (!playing || qaOpen || voiceOpen || sketchOn || quizMeOpen) return;
    const id = setTimeout(() => {
      setStep((s) => (s < total ? s + 1 : s));
    }, LESSON_AUTO_ADVANCE_MS);
    return () => clearTimeout(id);
  }, [step, playing, qaOpen, voiceOpen, sketchOn, quizMeOpen, total]);

  const onReact = (r: Reaction) => {
    setReactionMsg(r);
    tts.flush();
    tts.start({ text: r.msg });
    setTimeout(() => setReactionMsg(null), 3200);
  };

  /**
   * On every completed stroke: client-side recognize for immediate
   * feedback, then optionally POST the SVG/PNG to the backend. The
   * backend handler is stubbed (agent A2 will fully wire) so we just
   * fire-and-forget and ignore the SSE response for now.
   */
  const handleStrokeEnd = useCallback(
    async (stroke: SketchStroke) => {
      setStrokeCount((c) => c + 1);
      setLastStrokeAt(Date.now());
      const shape = recognition.recognize(stroke);
      if (shape) setRecognizedShape(shape);
      setStudentReply(null);

      // Best-effort backend call — silently ignore errors.
      if (!sessionId) return;
      try {
        // We send a minimal SVG path snapshot. The backend just needs
        // *something* to OCR; the real intelligence lives in agent A2.
        const svgSnippet = strokeToSvg(stroke);
        const blob = new Blob([svgSnippet], { type: 'image/svg+xml' });
        const fd = new FormData();
        fd.append('image', blob, 'sketch.svg');
        fd.append('question', '');
        // The endpoint expects PNG; sending SVG is best-effort during stub phase.
        await api(`/v1/sessions/${sessionId}/sketch`, {
          method: 'POST',
          body: fd,
        }).catch(() => undefined);
      } catch {
        // ignored
      }
    },
    [recognition, sessionId],
  );

  // Caption resolves through reaction → sketch → step content.
  const captionJsx = useMemo<ReactNode>(() => {
    if (reactionMsg) {
      return (
        <em style={{ fontStyle: 'normal', fontWeight: 600, color: 'var(--chalk-yellow)' }}>
          {reactionMsg.msg}
        </em>
      );
    }
    if (sketchOn && socraticMsg) {
      return (
        <em
          style={{ fontStyle: 'normal', fontWeight: 500, color: 'rgba(255,255,255,.92)' }}
        >
          {socraticMsg.text}
        </em>
      );
    }
    const cur = LESSON_STEPS[step];
    if (cur?.html) {
      return <MathContent html={cur.html} />;
    }
    return cur?.jsx ?? null;
  }, [reactionMsg, sketchOn, socraticMsg, step]);

  const captionWho = useMemo(() => {
    if (qaOpen || voiceOpen) return 'paused';
    if (sketchOn && socraticMsg) return socraticMsg.who;
    if (reactionMsg) return 'responding to you';
    if (playing) return 'speaking';
    return 'paused';
  }, [qaOpen, voiceOpen, sketchOn, socraticMsg, reactionMsg, playing]);

  const captionShowBars =
    speaking || (playing && !muted && !qaOpen && !voiceOpen);

  return (
    <div className="classroom" data-layout="immersive">
      <div className="cr-stage">
        <div className="cr-bg-dots" />
        <div className="cr-vignette" />

        {/* TOP CONTROLS */}
        <div className="cr-top">
          <button type="button" className="cr-back" onClick={() => router.push('/')}>
            <Icon name="prev" size={14} /> Exit lesson
          </button>
          <div className="cr-progress">
            <div className="cr-lesson">
              <em>{topic.unit}</em> {topic.title}
            </div>
            <div className="cr-dots">
              {LESSON_STEPS.slice(1).map((_, i) => {
                const idx = i + 1;
                const cls = step === idx ? 'active' : step > idx ? 'done' : '';
                return (
                  <div
                    key={i}
                    className={`cr-dot ${cls}`}
                    onClick={() => setStep(idx)}
                    role="button"
                    tabIndex={0}
                    aria-label={`Step ${idx}`}
                  />
                );
              })}
            </div>
            <PeerPresence />
          </div>
          <div className="cr-tools">
            <button
              type="button"
              className={`cr-tool ${sketchOn ? 'active' : ''}`}
              onClick={() => {
                setSketchOn((s) => !s);
                setPlaying(false);
                snapshotAndFlush();
              }}
              title="Sketch on the board"
            >
              ✏️
            </button>
            <button
              type="button"
              className="cr-tool"
              onClick={() => {
                setQuizMeOpen(true);
                setPlaying(false);
                snapshotAndFlush();
              }}
              title="Quiz me on this"
            >
              ⚡
            </button>
            <VoiceBar muted={muted} onMute={() => setMuted((m) => !m)} speaking={speaking} />
            <button
              type="button"
              className="cr-tool"
              onClick={() => setStep((s) => Math.max(1, s - 1))}
              title="Previous"
            >
              <Icon name="prev" size={14} />
            </button>
            <button
              type="button"
              className={`cr-tool ${playing ? 'active' : ''}`}
              onClick={() => setPlaying((p) => !p)}
              title="Play/Pause"
            >
              <Icon name={playing ? 'pause' : 'play'} size={14} />
            </button>
            <button
              type="button"
              className="cr-tool"
              onClick={() => setStep((s) => Math.min(total, s + 1))}
              title="Next"
            >
              <Icon name="next" size={14} />
            </button>
            <button
              type="button"
              className="cr-tool"
              onClick={() => setSidebarOpen((o) => !o)}
              title="Outline"
            >
              <Icon name="layout" size={14} />
            </button>
          </div>
        </div>

        {/* WHITEBOARD */}
        <div className="cr-board">
          <WhiteboardSVG step={step} />
        </div>

        {/* SKETCH LAYER */}
        <div className={`cr-sketch-wrap ${sketchOn ? 'active' : ''}`}>
          <SketchLayer
            active={sketchOn}
            color={sketchColor}
            eraser={sketchEraser}
            strokesApi={sketchApi.current}
            onStrokeStart={() => setLastStrokeAt(Date.now())}
            onStrokeEnd={handleStrokeEnd}
          />
        </div>
        <SketchToolbar
          visible={sketchOn}
          color={sketchColor}
          setColor={setSketchColor}
          eraser={sketchEraser}
          setEraser={setSketchEraser}
          onUndo={() => sketchApi.current.undo?.()}
          onClear={() => {
            sketchApi.current.clear?.();
            setStrokeCount(0);
            setRecognizedShape(null);
            recognition.reset();
          }}
          onClose={() => {
            setSketchOn(false);
            setPlaying(true);
          }}
          onHint={() => setHintsRequested((h) => h + 1)}
        />

        <ReplyBar
          visible={sketchOn}
          placeholder={
            socraticMsg?.text?.endsWith('?')
              ? 'Reply to Aria — type your thinking…'
              : 'Type to Aria, or ask a question…'
          }
          onSubmit={(t) => {
            setStudentReply(t);
            setRecognizedShape(null);
            if (sessionId) {
              api(`/v1/sessions/${sessionId}/reply`, {
                method: 'POST',
                json: { text: t },
              }).catch(() => undefined);
            }
          }}
          onVoice={() => setVoiceOpen(true)}
        />

        {/* Hover edge to summon the outline sidebar */}
        {!sidebarOpen && (
          <div
            className="cr-edge"
            onMouseEnter={() => setSidebarOpen(true)}
            onClick={() => setSidebarOpen(true)}
            role="button"
            tabIndex={-1}
            aria-label="Open outline"
          />
        )}

        {/* BOTTOM caption + asks */}
        <CaptionBar
          who={captionWho}
          showBars={captionShowBars}
          speaking={(playing || speaking) && !qaOpen && !voiceOpen}
          reacting={reactionMsg !== null}
          text={captionJsx}
          onAsk={() => {
            setQaOpen(true);
            setPlaying(false);
            snapshotAndFlush();
          }}
          onVoice={() => {
            setVoiceOpen(true);
            setPlaying(false);
            snapshotAndFlush();
          }}
        />

        {/* REACTIONS */}
        <ReactionsCluster onReact={onReact} />

        {/* VOICE MODE OVERLAY */}
        <VoiceMode
          active={voiceOpen}
          sessionId={sessionId}
          topic={topic.slug}
          // Server-streamed Aria audio (24 kHz Float32 PCM) is currently
          // dropped on the floor: `useTtsPlayback` still wraps
          // speechSynthesis (see A2's notes). When the playback worklet
          // takes over we'll forward each chunk via
          // `tts.pushAudio?.(samples)` here.
          // onAudioChunk={...}
          onInterrupted={() => {
            // Critical barge-in handling — drop any buffered Aria audio
            // immediately so the model's mid-sentence yield is audible.
            tts.flush();
          }}
          onCancel={() => {
            setVoiceOpen(false);
            // Lesson playback resumes via the step `useEffect`, which
            // re-runs when `voiceOpen` flips false and re-issues tts.start
            // with the bookmark offset captured by `snapshotAndFlush`.
            setPlaying(true);
          }}
          onSubmit={(text) => {
            setVoiceOpen(false);
            setQaInitialQ(text);
            setQaOpen(true);
          }}
        />

        {/* Q&A OVERLAY */}
        <QAOverlay
          active={qaOpen}
          initialQ={qaInitialQ}
          sessionId={sessionId}
          onClose={() => {
            setQaOpen(false);
            setQaInitialQ(null);
            setPlaying(true);
          }}
        />

        {/* QUIZ ME NOW */}
        <QuizMePop
          active={quizMeOpen}
          sessionId={sessionId}
          onClose={() => {
            setQuizMeOpen(false);
            setPlaying(true);
          }}
        />

        {/* SIDEBAR */}
        <div
          className={`cr-sidebar ${sidebarOpen ? 'open' : ''}`}
          onMouseLeave={() => setSidebarOpen(false)}
        >
          <div className="cr-sb-hd">
            <div className="ttl">Lesson outline</div>
            <button type="button" className="close" onClick={() => setSidebarOpen(false)}>
              <Icon name="close" size={14} />
            </button>
          </div>
          <div className="cr-aria-panel">
            <div className="wrap">
              <AriaMascot size={72} pulse withRing />
            </div>
            <div className="name">Prof. Aria</div>
            <div className="live">Teaching live</div>
          </div>
          <div className="cr-outline">
            <div className="cr-outline-ttl">Wave Properties · 8 steps</div>
            {LESSON_STEPS.slice(1).map((s, i) => {
              const idx = i + 1;
              const cls = step === idx ? 'active' : step > idx ? 'done' : '';
              return (
                <div
                  key={idx}
                  className={`cr-step ${cls}`}
                  onClick={() => setStep(idx)}
                  role="button"
                  tabIndex={0}
                >
                  <div className="cr-step-n">
                    {step > idx ? <Icon name="check" size={11} /> : idx}
                  </div>
                  <div className="cr-step-body">
                    <div className="cr-step-ttl">{STEP_TITLES[idx]}</div>
                    <div className="cr-step-time">{s.dur}</div>
                  </div>
                </div>
              );
            })}
          </div>
          <div
            style={{
              padding: '14px 16px',
              borderTop: '1px solid rgba(255,255,255,.06)',
            }}
          >
            <button
              type="button"
              className="btn btn-amber"
              style={{ width: '100%' }}
              onClick={() => {
                const path = `/classroom/quiz/${topic.slug}`;
                router.push(sessionId ? `${path}?session=${sessionId}` : path);
              }}
            >
              Skip to quiz →
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

/**
 * Serialize a single stroke into a tiny standalone SVG so we can POST
 * something to the backend during the stub phase. Production code will
 * rasterize the full sketch surface instead.
 */
function strokeToSvg(stroke: SketchStroke): string {
  const d = stroke.points
    .map((p, i) => `${i === 0 ? 'M' : 'L'}${p[0]},${p[1]}`)
    .join(' ');
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 700"><path d="${d}" fill="none" stroke="${stroke.color}" stroke-width="3"/></svg>`;
}
