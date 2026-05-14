import { QuizScreen } from './quiz-screen';

interface PageProps {
  params: Promise<{ topicId: string }>;
}

/** Quiz route — server shell, client island holds the state. */
export default async function QuizPage({ params }: PageProps) {
  const { topicId } = await params;
  return <QuizScreen topicId={topicId} />;
}
