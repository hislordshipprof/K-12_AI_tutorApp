import type { Metadata } from 'next';

import { LegalPage, LegalSection } from '../_components/legal-page';

export const metadata: Metadata = {
  title: 'Privacy Policy — EduMind',
  description:
    'How EduMind collects, uses, and protects student data. Draft pending legal review.',
};

/**
 * Privacy Policy — static marketing page (`/privacy`).
 *
 * Placeholder content for a K-12 ed-tech product handling minors' data.
 * Surfaced from the sign-up form. NOT legal advice — see the draft notice
 * rendered by `LegalPage`.
 */
export default function PrivacyPolicyPage() {
  return (
    <LegalPage title="Privacy Policy" lastUpdated="15 May 2026">
      <p>
        EduMind is an AI tutoring product used by K-12 students. Because our
        users are children, protecting their personal information is central
        to how we build the product. This policy explains what we collect,
        why, and the choices you have.
      </p>

      <LegalSection heading="1. Who we are">
        <p>
          EduMind provides AI-guided lessons (delivered by our tutor, &ldquo;
          Aria&rdquo;) to students, generally as part of a school or
          classroom. In most cases a school or teacher introduces EduMind to
          students and acts as the consenting party on a parent&apos;s behalf.
        </p>
      </LegalSection>

      <LegalSection heading="2. What data we collect">
        <p>We deliberately collect only what teaching requires:</p>
        <ul className="ml-5 list-disc space-y-1">
          <li>
            <span className="font-semibold">Account details</span> — the
            student&apos;s name and email address, and a password.
          </li>
          <li>
            <span className="font-semibold">Learning progress</span> — which
            lessons and topics have been started or completed, quiz scores,
            time spent, and streaks.
          </li>
          <li>
            <span className="font-semibold">Learning interactions</span> — the
            questions a student asks Aria and the answers given, so the lesson
            can adapt.
          </li>
        </ul>
        <p>
          We do <span className="font-semibold">not</span> collect a date of
          birth beyond a general age band, a home address, a phone number, or
          other personal information that teaching does not need.
        </p>
      </LegalSection>

      <LegalSection heading="3. Children's privacy (COPPA & FERPA)">
        <p>
          EduMind is built for minors, so US child-data laws apply. Under{' '}
          <span className="font-semibold">COPPA</span> (the Children&apos;s
          Online Privacy Protection Act), collecting personal information from
          a child under 13 requires verifiable parental consent; in a school
          setting the school may provide that consent on a parent&apos;s
          behalf. Under <span className="font-semibold">FERPA</span> (the
          Family Educational Rights and Privacy Act), student education records
          belong to the school and the family, and we handle them as a service
          provider to the school. We aim to support schools in meeting these
          obligations and to act only on instructions consistent with them.
        </p>
      </LegalSection>

      <LegalSection heading="4. How we use data">
        <p>
          We use the data above to deliver lessons, adapt tutoring to the
          student, show progress to the student and (where applicable) their
          teacher, and keep the service secure and working. We do not sell
          personal information, and we do not use student data for
          advertising.
        </p>
      </LegalSection>

      <LegalSection heading="5. AI processing & sub-processors">
        <p>
          Aria is powered by a third-party AI model. To generate a lesson or
          answer a question, the relevant text a student types may be sent to
          that model provider for processing. We work to limit what is sent
          and ask students not to type personal information into questions.
          A full review of sub-processors and their terms is part of our
          pre-launch compliance work.
        </p>
      </LegalSection>

      <LegalSection heading="6. Your right to deletion">
        <p>
          A signed-in user can delete their EduMind account at any time from
          the account menu. Deleting an account removes the profile, learning
          progress, quiz attempts, notes, and learning-interaction records
          associated with it. Schools may also request deletion of a
          student&apos;s data when the student leaves a class or a class is
          archived.
        </p>
      </LegalSection>

      <LegalSection heading="7. Data security & retention">
        <p>
          We store data with a reputable cloud provider and restrict access to
          what is needed to operate the service. We keep personal data only as
          long as it is needed to provide EduMind, and delete it on request as
          described above.
        </p>
      </LegalSection>

      <LegalSection heading="8. Contact">
        <p>
          Questions about this policy or about a student&apos;s data can be
          sent to your school&apos;s EduMind administrator, or to the EduMind
          team at the address provided to your school.
        </p>
      </LegalSection>
    </LegalPage>
  );
}
