import { headers } from 'next/headers';

import { ClassroomShell, type ClassroomTopic } from '@/components/classroom/classroom-shell';

interface PageProps {
  params: Promise<{ topicId: string }>;
}

interface TopicDetails {
  id: string | null;
  slug: string;
  name: string;
  unit_n: number | null;
  unit_name: string;
  course_slug: string | null;
  has_content: boolean;
  content: Array<{ tts: string; html: string; dur: string }> | null;
}

/**
 * Classroom entry point. The `topicId` URL segment can be:
 *   - a real topic UUID (the dashboard links here),
 *   - a legacy slug like `wave-properties-anatomy` (kept for back-compat
 *     with the prototype + Playwright fixtures).
 *
 * Server component — fetches the topic from `/v1/topics/{id_or_slug}`
 * and hands the resolved metadata to the `ClassroomShell` client island.
 * The endpoint already returns a graceful fallback when the lookup
 * misses, so this code path never throws.
 */
export default async function ClassroomPage({ params }: PageProps) {
  const { topicId } = await params;

  const apiBase =
    process.env.NEXT_PUBLIC_API_BASE ?? process.env.API_BASE_URL ?? '';
  // UUID route params get a clean "Lesson" placeholder rather than a
  // mangled hex string while the API fetch resolves.
  const isUuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
    topicId,
  );
  let topic: ClassroomTopic = {
    slug: topicId,
    unit: 'Unit',
    title: isUuid
      ? 'Lesson'
      : topicId.replace(/-/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()),
  };

  if (apiBase) {
    try {
      const headerList = await headers();
      const cookie = headerList.get('cookie');
      const res = await fetch(`${apiBase}/v1/topics/${encodeURIComponent(topicId)}`, {
        headers: cookie ? { cookie } : {},
        cache: 'no-store',
      });
      if (res.ok) {
        const details = (await res.json()) as TopicDetails;
        topic = {
          slug: details.id ?? details.slug,
          unit: details.unit_n ? `Unit ${details.unit_n}` : details.unit_name,
          title: details.name,
          content: details.content ?? null,
        };
      }
    } catch {
      // Network blip — keep the derived fallback so the page still renders.
    }
  }

  return <ClassroomShell topic={topic} />;
}
