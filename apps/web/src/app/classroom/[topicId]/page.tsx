import { ClassroomShell, type ClassroomTopic } from '@/components/classroom/classroom-shell';

interface PageProps {
  params: Promise<{ topicId: string }>;
}

/**
 * Static topic catalog — keyed by slug. The backend `/v1/topics/{slug}`
 * endpoint isn't wired yet so we render from this map.
 */
const TOPICS: Record<string, ClassroomTopic> = {
  'wave-properties-anatomy': {
    slug: 'wave-properties-anatomy',
    unit: 'Unit 4',
    title: 'Wave Properties & Anatomy',
  },
};

/**
 * Classroom entry point. The `topicId` is a URL-safe slug.
 *
 * Server component — picks the topic and hands it off to the
 * `ClassroomShell` client island.
 */
export default async function ClassroomPage({ params }: PageProps) {
  const { topicId } = await params;
  const topic =
    TOPICS[topicId] ?? {
      slug: topicId,
      unit: 'Unit',
      title: topicId.replace(/-/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()),
    };
  return <ClassroomShell topic={topic} />;
}

// Pre-render the canonical slug so it's instant on first hit.
export function generateStaticParams() {
  return Object.keys(TOPICS).map((topicId) => ({ topicId }));
}
