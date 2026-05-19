'use client';

import { useQuery } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';

import { AriaMascot } from '@/components/aria/aria-mascot';
import { Icon } from '@/components/aria/icon';
import { QAOverlay } from '@/components/classroom/qa-overlay';
import { QuizMePop } from '@/components/classroom/quiz-me-pop';
import { ReactionsCluster, type Reaction } from '@/components/classroom/reactions-cluster';
import { ReplyBar } from '@/components/classroom/reply-bar';
import { SketchLayer, type SketchApi } from '@/components/classroom/sketch-layer';
import { SketchToolbar } from '@/components/classroom/sketch-toolbar';
import { TranscriptPanel, type TranscriptTurn } from '@/components/classroom/transcript-panel';
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
  /**
   * Optional animated diagram for this step (Phase B). When present the
   * whiteboard renders the matching scene component instead of the
   * generic text chalkboard. `type` is a key in the scene registry.
   */
  scene?: { type: string; params: Record<string, unknown> } | null;
  /**
   * `topic_pages` row id — set on a step a teacher lesson teaches over
   * a real slide. The whiteboard renders that slide as the backdrop
   * (`teacher-authoring.md` §7); steps with no `page` fall back to the
   * chalkboard.
   */
  page?: string | null;
}

// Placeholder shown when a real topic has no generated `content` yet (the
// content pipeline fills `topics.content` asynchronously). It is NOT lesson
// content — just a holding step so the classroom renders instead of going
// blank. The old hardcoded `wave-properties-anatomy` prototype lesson was
// removed: real topics carry their own `content` from the DB.
const LESSON_STEPS: LessonStep[] = [
  { jsx: 'Preparing your lesson…', tts: 'Preparing your lesson.', dur: '00:00' },
  {
    jsx: 'Aria is getting this lesson ready — hang tight.',
    tts: 'Aria is getting this lesson ready. Hang tight.',
    dur: '00:00',
  },
];

// Steps normally advance when Aria finishes narrating (TTS `onEnded`).
// This is only a safety net: if both audio AND speechSynthesis fail to
// fire a completion event, don't let a step hang forever.
const LESSON_SAFETY_ADVANCE_MS = 90_000;

// Outline titles for the placeholder steps above. Real topics derive their
// outline from `topics.content` (see `stepTitles` below).
const STEP_TITLES = ['', 'Preparing'];

export interface ClassroomTopic {
  slug: string;
  unit: string;
  title: string;
  /**
   * Lesson steps from `topics.content` jsonb when the route resolves to a
   * real DB topic. Each step matches the schema produced by the content
   * pipeline: `{tts, html, dur}`. When null, the hardcoded `LESSON_STEPS`
   * fallback below renders so the prototype + Playwright fixtures still
   * work.
   */
  content?: Array<{
    tts: string;
    html: string;
    dur: string;
    scene?: { type: string; params: Record<string, unknown> } | null;
    page?: string | null;
  }> | null;
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

  // Prefer the real lesson content from `topics.content` when present;
  // fall back to the generic "preparing" placeholder otherwise. The shape
  // is identical so downstream playback/MathContent code is unchanged.
  const lessonSteps: LessonStep[] = useMemo(() => {
    if (topic.content && topic.content.length > 0) {
      return topic.content.map((s) => ({
        html: s.html,
        tts: s.tts,
        dur: s.dur,
        scene: s.scene ?? null,
        page: s.page ?? null,
      }));
    }
    return LESSON_STEPS;
  }, [topic.content]);
  // The hand-drawn wave SVG is only meaningful for wave / oscillation
  // topics. Everything else gets a generic chalkboard that surfaces the
  // current step's highlighted phrase, so a Kinematics lesson doesn't
  // render a sine wave on the board.
  const whiteboardKind: 'waves' | 'generic' = useMemo(() => {
    const t = topic.title.toLowerCase();
    if (t.includes('wave') || t.includes('oscillation')) {
      return 'waves';
    }
    return 'generic';
  }, [topic.title]);

  const stepTitles: string[] = useMemo(() => {
    if (topic.content && topic.content.length > 0) {
      return topic.content.map((s, i) => {
        if (i === 0) return '';
        // Derive a short title from the html by stripping tags + LaTeX +
        // truncating. Keeps the outline readable without a separate field.
        const plain = s.html
          .replace(/<[^>]+>/g, '')
          .replace(/\$\$[^$]+\$\$/g, '')
          .replace(/\$[^$]+\$/g, '')
          .trim();
        return plain.split(/[.?!]/)[0]?.slice(0, 36) || `Step ${i}`;
      });
    }
    return STEP_TITLES;
  }, [topic.content]);

  // Start on the first real lesson step (index 0 is the intro/placeholder).
  // Clamp so a short lesson — e.g. the 2-step "preparing" placeholder —
  // never starts out of bounds.
  const [step, setStep] = useState(() =>
    Math.min(1, Math.max(0, lessonSteps.length - 1)),
  );
  const [playing, setPlaying] = useState(true);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  // The live transcript panel is docked on the right and open by default.
  const [transcriptCollapsed, setTranscriptCollapsed] = useState(false);
  const [qaOpen, setQaOpen] = useState(false);
  const [qaInitialQ, setQaInitialQ] = useState<string | null>(null);
  const [voiceOpen, setVoiceOpen] = useState(false);
  const [muted, setMuted] = useState(true);
  const [reactionMsg, setReactionMsg] = useState<Reaction | null>(null);
  // Visibility of the reactions cluster — opened by the bottom-dock "React".
  const [reactionsOpen, setReactionsOpen] = useState(true);

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

  const total = lessonSteps.length - 1;

  // Slide backdrop for teacher lessons — a step with a `page` is taught
  // over a real slide image. The API mints a short-lived signed URL for
  // the private `lesson-materials` object; chalkboard steps have no
  // `page` and skip the fetch (`teacher-authoring.md` §7).
  const currentPage = lessonSteps[step]?.page ?? null;
  const slideQuery = useQuery({
    queryKey: ['topic-slide', topic.slug, currentPage],
    queryFn: () =>
      api<{ url: string }>(`/v1/topics/${topic.slug}/slide/${currentPage}`),
    enabled: Boolean(currentPage),
    staleTime: 30 * 60_000,
    retry: false,
  });
  const slideUrl = currentPage ? slideQuery.data?.url ?? null : null;

  const tts = useTtsPlayback({ muted, rate: 1 });
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
    const s = lessonSteps[step];
    if (!s) return;
    const resumeFromMs =
      bookmark && bookmark.stepIndex === step ? bookmark.audioOffsetMs : 0;
    tts.start({
      text: s.tts,
      startMs: resumeFromMs,
      // Smooth playback: advance to the next step only once Aria has
      // actually finished narrating this one — never mid-sentence.
      onEnded: () => setStep((x) => (x < total ? x + 1 : x)),
    });
    // Bookmark has been consumed — clear so subsequent step changes start fresh.
    if (resumeFromMs > 0) setBookmark(null);
    // Warm the next step's TTS so the ~3-5s Gemini Live latency hides
    // inside the current step's playback. Best-effort; muted users skip.
    const nextStep = lessonSteps[step + 1];
    if (nextStep) tts.prefetch(nextStep.tts);
    return () => tts.flush();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step, playing, qaOpen, voiceOpen, sketchOn, quizMeOpen, muted]);

  // Safety net only — the real step advance is driven by TTS completion
  // (the `onEnded` callback in the speak effect above). This guards
  // against a step stalling forever if a completion event never fires.
  useEffect(() => {
    if (!playing || qaOpen || voiceOpen || sketchOn || quizMeOpen) return;
    const id = setTimeout(() => {
      setStep((s) => (s < total ? s + 1 : s));
    }, LESSON_SAFETY_ADVANCE_MS);
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

  // Word-reveal progress for the caption + chalkboard. When the lesson is
  // muted or paused there's no audio clock to sync to, so we show the
  // content fully revealed; while playing unmuted it tracks the TTS
  // audio progress so words "write themselves" as Aria speaks.
  const captionProgress = muted || !playing ? 1 : tts.progress;

  // Live transcript turns — derived from the real lesson, not faked. Every
  // lesson step the student has reached becomes an Aria narration turn; the
  // current step is the one that streams in word-by-word (driven by
  // `captionProgress`). Step 0 is the intro placeholder and is skipped.
  // The panel structure also supports student turns; voice/reply capture
  // isn't wired into this v1, so only Aria narration turns are emitted.
  const transcriptTurns = useMemo<TranscriptTurn[]>(() => {
    const turns: TranscriptTurn[] = [];
    for (let i = 1; i <= step && i < lessonSteps.length; i += 1) {
      const s = lessonSteps[i];
      if (!s) continue;
      const isCurrent = i === step;
      turns.push({
        id: `step-${i}`,
        who: 'aria',
        text: s.tts,
        html: isCurrent ? s.html : undefined,
        current: isCurrent,
      });
    }
    return turns;
  }, [lessonSteps, step]);

  // Aria is "speaking" in the transcript whenever lesson narration is the
  // active modality (not paused, no overlay stealing focus).
  const transcriptAriaSpeaking =
    playing && !qaOpen && !voiceOpen && !sketchOn && !quizMeOpen;

  return (
    <div className="classroom flex flex-col" data-layout="immersive">
      {/* ─────────────── TOP APP BAR ─────────────── */}
      <header className="flex justify-between items-center w-full px-6 py-3 z-50 shrink-0">
        {/* Left: Exit lesson */}
        <button
          type="button"
          onClick={() => router.push('/dashboard')}
          className="flex items-center gap-2 pl-3 pr-5 py-2.5 rounded-full bg-[#0d1c2d] border border-[#909097]/25 hover:border-[#ffb4ab]/50 hover:bg-[#ffb4ab]/10 transition-all text-[#c6c6cd] hover:text-[#ffb4ab]"
        >
          <span className="material-symbols-outlined text-[20px]">chevron_left</span>
          <span className="text-[13px] font-semibold">Exit lesson</span>
        </button>

        {/* Center: unit info + step progress dots */}
        <div className="flex flex-col items-center bg-[#122131]/50 backdrop-blur-md border border-white/10 rounded-2xl px-7 py-2 shadow-lg">
          <div className="flex items-center gap-2 mb-2">
            <span className="text-[11px] font-bold tracking-[0.12em] text-[#ffb95f] uppercase">
              {topic.unit}
            </span>
            <span className="text-[12px] text-[#c6c6cd]">{topic.title}</span>
          </div>
          <div className="flex gap-1.5">
            {lessonSteps.slice(1).map((_, i) => {
              const idx = i + 1;
              const isActive = step === idx;
              const isDone = step > idx;
              return (
                <button
                  key={idx}
                  type="button"
                  onClick={() => setStep(idx)}
                  aria-label={`Step ${idx}`}
                  className={`h-1.5 rounded-full transition-all ${
                    isActive
                      ? 'w-5 bg-[#7bd0ff]'
                      : isDone
                        ? 'w-1.5 bg-[#ffb95f]'
                        : 'w-1.5 bg-[#273647] hover:bg-[#45464d]'
                  }`}
                />
              );
            })}
          </div>
        </div>

        {/* Right: playback + view controls */}
        <div className="flex items-center gap-1.5">
          <div className="flex items-center gap-1 bg-[#0d1c2d] rounded-full p-1 border border-white/5">
            <button
              type="button"
              onClick={() => setStep((s) => Math.max(1, s - 1))}
              title="Previous step"
              className="w-9 h-9 rounded-full flex items-center justify-center hover:bg-[#273647] transition-colors text-[#c6c6cd]"
            >
              <span className="material-symbols-outlined text-[20px]">skip_previous</span>
            </button>
            <button
              type="button"
              onClick={() => setPlaying((p) => !p)}
              title={playing ? 'Pause' : 'Play'}
              className="w-10 h-10 rounded-full bg-[#ffb95f]/20 text-[#ffb95f] flex items-center justify-center hover:bg-[#ffb95f]/30 transition-colors"
            >
              <span className="material-symbols-outlined fill text-[22px]">
                {playing ? 'pause' : 'play_arrow'}
              </span>
            </button>
            <button
              type="button"
              onClick={() => setStep((s) => Math.min(total, s + 1))}
              title="Next step"
              className="w-9 h-9 rounded-full flex items-center justify-center hover:bg-[#273647] transition-colors text-[#c6c6cd]"
            >
              <span className="material-symbols-outlined text-[20px]">skip_next</span>
            </button>
          </div>
          {/* Mute toggle */}
          <button
            type="button"
            onClick={() => setMuted((m) => !m)}
            aria-pressed={!muted}
            title={muted ? 'Unmute Aria' : 'Mute Aria'}
            className="w-10 h-10 rounded-full bg-[#122131] flex items-center justify-center hover:bg-[#273647] transition-colors text-[#c6c6cd]"
          >
            <span className="material-symbols-outlined text-[20px]">
              {muted ? 'volume_off' : 'volume_up'}
            </span>
          </button>
          {/* Transcript panel toggle */}
          <button
            type="button"
            onClick={() => setTranscriptCollapsed((c) => !c)}
            title="Toggle transcript"
            className={`w-10 h-10 rounded-full flex items-center justify-center transition-colors ${
              !transcriptCollapsed
                ? 'bg-[#00a6e0]/25 text-[#7bd0ff] hover:bg-[#00a6e0]/35'
                : 'bg-[#122131] text-[#c6c6cd] hover:bg-[#273647]'
            }`}
          >
            <span className="material-symbols-outlined text-[20px]">
              {transcriptCollapsed ? 'right_panel_open' : 'right_panel_close'}
            </span>
          </button>
          {/* Outline sidebar toggle */}
          <button
            type="button"
            onClick={() => setSidebarOpen((o) => !o)}
            title="Lesson overview"
            className={`w-10 h-10 rounded-full flex items-center justify-center transition-colors ${
              sidebarOpen
                ? 'bg-[#ffb95f]/20 text-[#ffb95f] hover:bg-[#ffb95f]/30'
                : 'bg-[#122131] text-[#c6c6cd] hover:bg-[#273647]'
            }`}
          >
            <span className="material-symbols-outlined text-[20px]">grid_view</span>
          </button>
        </div>
      </header>

      {/* ─────────────── MAIN ─────────────── */}
      <main className="flex-1 flex overflow-hidden px-6 gap-5 pb-28 min-h-0 relative">
        {/* Left floating annotation rail — always docked */}
        <nav className="absolute left-7 top-1/2 -translate-y-1/2 z-40 w-14 bg-[#122131]/40 backdrop-blur-xl rounded-full py-3 flex flex-col items-center gap-1 border border-white/10 shadow-lg">
          <button
            type="button"
            onClick={() => {
              if (!sketchOn) {
                setSketchOn(true);
                setPlaying(false);
                snapshotAndFlush();
              }
              setSketchEraser(false);
            }}
            title="Pen"
            className={`w-10 h-10 rounded-full flex items-center justify-center transition-all ${
              sketchOn && !sketchEraser
                ? 'bg-[#00a6e0] text-[#00374d] shadow-[0_0_14px_rgba(0,166,224,0.45)]'
                : 'text-[#c6c6cd] hover:text-[#7bd0ff] hover:bg-white/5'
            }`}
          >
            <span className={`material-symbols-outlined text-[21px] ${sketchOn && !sketchEraser ? 'fill' : ''}`}>
              edit
            </span>
          </button>
          <button
            type="button"
            onClick={() => {
              if (!sketchOn) {
                setSketchOn(true);
                setPlaying(false);
                snapshotAndFlush();
              }
              setSketchEraser(false);
            }}
            title="Marker"
            className="w-10 h-10 rounded-full flex items-center justify-center text-[#c6c6cd] hover:text-[#7bd0ff] hover:bg-white/5 transition-all"
          >
            <span className="material-symbols-outlined text-[21px]">brush</span>
          </button>
          <button
            type="button"
            onClick={() => {
              if (!sketchOn) {
                setSketchOn(true);
                setPlaying(false);
                snapshotAndFlush();
              }
              setSketchEraser(false);
            }}
            title="Highlighter"
            className="w-10 h-10 rounded-full flex items-center justify-center text-[#c6c6cd] hover:text-[#7bd0ff] hover:bg-white/5 transition-all"
          >
            <span className="material-symbols-outlined text-[21px]">ink_highlighter</span>
          </button>
          <button
            type="button"
            onClick={() => {
              if (!sketchOn) {
                setSketchOn(true);
                setPlaying(false);
                snapshotAndFlush();
              }
              setSketchEraser(true);
            }}
            title="Eraser"
            className={`w-10 h-10 rounded-full flex items-center justify-center transition-all ${
              sketchOn && sketchEraser
                ? 'bg-[#00a6e0] text-[#00374d] shadow-[0_0_14px_rgba(0,166,224,0.45)]'
                : 'text-[#c6c6cd] hover:text-[#7bd0ff] hover:bg-white/5'
            }`}
          >
            <span className="material-symbols-outlined text-[21px]">ink_eraser</span>
          </button>
          <div className="w-6 h-px bg-white/10 my-1" />
          {/* Colour swatch — cycles through the sketch palette */}
          <button
            type="button"
            onClick={() => {
              const palette = [
                'rgba(255,255,255,.85)',
                '#ffb95f',
                '#7bd0ff',
                '#f09aaf',
                '#7dd4a8',
              ];
              setSketchColor((c) => {
                const i = palette.indexOf(c);
                return palette[(i + 1) % palette.length] ?? palette[0]!;
              });
            }}
            title="Cycle pen colour"
            className="w-7 h-7 rounded-full ring-2 ring-white/40"
            style={{ background: sketchColor }}
          />
          <button
            type="button"
            onClick={() => {
              sketchApi.current.clear?.();
              setStrokeCount(0);
              setRecognizedShape(null);
              recognition.reset();
            }}
            title="Clear board"
            className="w-10 h-10 rounded-full flex items-center justify-center text-[#c6c6cd] hover:text-[#ffb4ab] hover:bg-white/5 transition-all"
          >
            <span className="material-symbols-outlined text-[21px]">delete</span>
          </button>
        </nav>

        {/* Center: the slide. White card behind a teacher slide image;
            the dark board colour behind the chalk-style WhiteboardSVG so
            its light chalk content stays legible. */}
        <section
          className={`flex-1 ml-16 rounded-2xl overflow-hidden shadow-2xl relative flex items-center justify-center p-6 min-w-0 ${
            slideUrl ? 'bg-white' : 'bg-[#0E1A2E]'
          }`}
        >
          <WhiteboardSVG
            step={step}
            kind={whiteboardKind}
            stepHtml={lessonSteps[step]?.html}
            stepTts={lessonSteps[step]?.tts}
            topicTitle={topic.title}
            revealProgress={captionProgress}
            scene={lessonSteps[step]?.scene ?? null}
            slideUrl={slideUrl}
            className="w-full h-full max-w-[1100px]"
          />
          <div className="absolute bottom-4 right-5 text-xs text-gray-400 font-medium">
            Step {step} / {total}
          </div>
        </section>

        {/* Right: live transcript panel */}
        <TranscriptPanel
          turns={transcriptTurns}
          progress={captionProgress}
          ariaSpeaking={transcriptAriaSpeaking}
          listening={voiceOpen}
          collapsed={transcriptCollapsed}
          onCollapse={() => setTranscriptCollapsed(true)}
        />
      </main>

      {/* ─────────────── BOTTOM DOCK ─────────────── */}
      <footer className="fixed bottom-0 left-0 w-full z-40 flex justify-center pb-6 px-6 pointer-events-none">
        <div className="flex items-center gap-2.5 bg-[#122131]/55 backdrop-blur-xl rounded-2xl p-2.5 border border-white/10 shadow-2xl pointer-events-auto">
          <button
            type="button"
            onClick={() => {
              setQaOpen(true);
              setPlaying(false);
              snapshotAndFlush();
            }}
            className="flex flex-col items-center justify-center gap-0.5 w-[68px] h-16 rounded-xl hover:bg-white/5 transition-all text-[#c6c6cd] hover:text-[#d4e4fa]"
          >
            <span className="material-symbols-outlined text-[22px]">chat_bubble</span>
            <span className="text-[11px] font-semibold">Chat</span>
          </button>
          <button
            type="button"
            onClick={() => {
              setQuizMeOpen(true);
              setPlaying(false);
              snapshotAndFlush();
            }}
            className="flex flex-col items-center justify-center gap-0.5 w-[68px] h-16 rounded-xl hover:bg-white/5 transition-all text-[#c6c6cd] hover:text-[#d4e4fa]"
          >
            <span className="material-symbols-outlined text-[22px]">bolt</span>
            <span className="text-[11px] font-semibold">Quiz me</span>
          </button>

          <div className="w-px h-10 bg-white/10 mx-1" />

          {/* PRIMARY: raise hand / talk to Aria */}
          <button
            type="button"
            onClick={() => {
              setVoiceOpen(true);
              setPlaying(false);
              snapshotAndFlush();
            }}
            className="cr-pulse-raise flex items-center gap-3 pl-6 pr-7 h-16 rounded-xl bg-[#ffb95f] text-[#472a00] hover:brightness-110 transition-all shadow-[0_0_28px_rgba(255,185,95,0.35)]"
          >
            <span className="material-symbols-outlined fill text-[28px]">pan_tool</span>
            <span className="flex flex-col items-start leading-tight">
              <span className="text-[14px] font-bold">Raise hand</span>
              <span className="text-[10px] opacity-75 font-medium">Talk to Aria</span>
            </span>
          </button>

          <div className="w-px h-10 bg-white/10 mx-1" />

          <button
            type="button"
            onClick={() => setReactionsOpen(true)}
            className="flex flex-col items-center justify-center gap-0.5 w-[68px] h-16 rounded-xl hover:bg-white/5 transition-all text-[#c6c6cd] hover:text-[#d4e4fa]"
          >
            <span className="material-symbols-outlined text-[22px]">mood</span>
            <span className="text-[11px] font-semibold">React</span>
          </button>
          <button
            type="button"
            onClick={() => setMuted((m) => !m)}
            aria-pressed={!muted}
            className={`flex flex-col items-center justify-center gap-0.5 w-[68px] h-16 rounded-xl transition-all ${
              muted
                ? 'text-[#c6c6cd] hover:bg-white/5 hover:text-[#d4e4fa]'
                : 'bg-[#00a6e0]/15 hover:bg-[#00a6e0]/25 text-[#7bd0ff]'
            }`}
          >
            <span className="material-symbols-outlined text-[22px]">
              {muted ? 'mic_off' : 'mic'}
            </span>
            <span className="text-[11px] font-semibold">{muted ? 'Mic off' : 'Mic on'}</span>
          </button>
        </div>
      </footer>

      {/* ─────────────── OVERLAYS ─────────────── */}
      {/* SKETCH LAYER — sits above the new layout */}
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

      {/* REACTIONS */}
      <ReactionsCluster
        onReact={onReact}
        open={reactionsOpen}
        onOpenChange={setReactionsOpen}
      />

      {/* VOICE MODE OVERLAY */}
      <VoiceMode
        active={voiceOpen}
        sessionId={sessionId}
        topic={topic.slug}
        onInterrupted={() => {
          tts.flush();
        }}
        onCancel={() => {
          setVoiceOpen(false);
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
        stepIndex={step}
        slideText={lessonSteps[step]?.html ?? lessonSteps[step]?.tts ?? ''}
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

      {/* OUTLINE SIDEBAR */}
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
            <AriaMascot size={64} pulse withRing />
          </div>
          <div className="name">Prof. Aria</div>
          <div className="live">Teaching live</div>
        </div>
        <div className="cr-outline">
          <div className="cr-outline-ttl">
            {topic.title} · {lessonSteps.length - 1} steps
          </div>
          {lessonSteps.slice(1).map((s, i) => {
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
                  <div className="cr-step-ttl">{stepTitles[idx]}</div>
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
