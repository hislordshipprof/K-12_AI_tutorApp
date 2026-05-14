import { CompleteScreen } from './complete-screen';

interface PageProps {
  params: Promise<{ sessionId: string }>;
}

/** Lesson-complete celebration screen. */
export default async function CompletePage({ params }: PageProps) {
  const { sessionId } = await params;
  return <CompleteScreen sessionId={sessionId} />;
}
