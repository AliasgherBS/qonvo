import type { Metadata } from "next";
import Link from "next/link";

import { LegalPage, MarketingShell, Section } from "@/components/marketing-shell";
import { GOOGLE_LIMITED_USE, LEGAL } from "@/lib/legal";

export const metadata: Metadata = {
  title: "Privacy Policy",
  description:
    "How Qonvo collects, uses, stores, and shares data, including data accessed through Google APIs.",
};

export default function PrivacyPage() {
  return (
    <MarketingShell>
      <LegalPage title="Privacy Policy">
        <p className="text-muted-foreground">
          This policy explains what {LEGAL.companyName} (&ldquo;Qonvo&rdquo;, &ldquo;we&rdquo;)
          collects, why, how long we keep it, and who else sees it. It covers both the business
          owners who sign up for Qonvo (&ldquo;you&rdquo;) and the customers who message their
          WhatsApp number (&ldquo;end customers&rdquo;).
        </p>

        <Section title="Who we are">
          <p>
            Qonvo is operated by {LEGAL.legalEntity}, based in {LEGAL.jurisdiction}. For any privacy
            question or request, contact{" "}
            <a href={`mailto:${LEGAL.privacyEmail}`} className="text-primary-strong hover:underline">
              {LEGAL.privacyEmail}
            </a>
            .
          </p>
        </Section>

        <Section title="What we collect">
          <p>
            <strong className="text-foreground">Account data.</strong> Your name, email address,
            business name, and password (stored only as an Argon2 hash, so we never see it). If you
            sign in with Google, we receive your email address and display name instead of a
            password.
          </p>
          <p>
            <strong className="text-foreground">Business knowledge.</strong> Whatever you add to
            Qonvo so it can answer questions: hours, prices, policies, documents, and settings.
          </p>
          <p>
            <strong className="text-foreground">Conversations.</strong> Messages exchanged between
            your WhatsApp number and your end customers, including their phone number, message text,
            and any voice notes. Voice notes are transcribed to text so the assistant can respond.
          </p>
          <p>
            <strong className="text-foreground">Operational data.</strong> Logs, timestamps, error
            reports, and usage counts we need to run and debug the service.
          </p>
          <p>
            We do not intentionally collect special-category data (health, financial account
            credentials, government identifiers). Please do not put such data into Qonvo&apos;s
            knowledge base.
          </p>
        </Section>

        <Section title="Google user data we access">
          <p>
            Google access is entirely optional. Nothing below happens unless you explicitly connect
            your Google account, and you can disconnect at any time.
          </p>
          <p>
            <strong className="text-foreground">Sign in with Google</strong>:{" "}
            <code className="rounded bg-surface-muted px-1 py-0.5 text-xs">openid</code>,{" "}
            <code className="rounded bg-surface-muted px-1 py-0.5 text-xs">email</code>,{" "}
            <code className="rounded bg-surface-muted px-1 py-0.5 text-xs">profile</code>. We read
            your email address and name solely to create and identify your Qonvo account.
          </p>
          <p>
            <strong className="text-foreground">Google Calendar</strong>:{" "}
            <code className="rounded bg-surface-muted px-1 py-0.5 text-xs">
              calendar.app.created
            </code>{" "}
            lets Qonvo create a single calendar named &ldquo;Qonvo Bookings&rdquo; in your account
            and read or write events <em>only on that calendar</em>. It cannot see or change your
            other calendars.{" "}
            <code className="rounded bg-surface-muted px-1 py-0.5 text-xs">calendar.freebusy</code>{" "}
            lets it read your busy/free time blocks: start and end times only, never event titles,
            attendees or descriptions, so it does not book a customer over an existing
            commitment.
          </p>
          <p>
            <strong className="text-foreground">Google Sheets and Drive</strong>:{" "}
            <code className="rounded bg-surface-muted px-1 py-0.5 text-xs">drive.file</code> grants
            per-file access. Qonvo can only open a spreadsheet you personally select in the Google
            file chooser, or one it created for you. It cannot list, read, or search anything else in
            your Drive. We use this to append leads and orders to the sheet you chose and to read
            rows back when a customer asks about stock, pricing, or order status.
          </p>
          <p>
            We request the narrowest scopes that make these features work, and we ask for Calendar
            and Sheets access separately, only when you turn that feature on.
          </p>
        </Section>

        <Section title="How we use it">
          <p>
            To operate the service: generating replies to your end customers, booking appointments,
            recording leads and orders, sending you alerts, and providing your dashboard and
            analytics. We also use operational data to keep the service secure and reliable.
          </p>
          <p>
            We do <strong className="text-foreground">not</strong> use your data, your end
            customers&apos; messages, or any Google user data to train machine-learning models, and
            we do not sell data or use it for advertising.
          </p>
        </Section>

        <Section title="Google API Services Limited Use">
          <p className="rounded-2xl border border-border bg-surface-muted px-4 py-3 text-foreground">
            {GOOGLE_LIMITED_USE}
          </p>
          <p>
            Concretely: we use Google user data only to provide the features you enabled, we never
            transfer it to others except as described below, we never use it for advertising, and no
            human at Qonvo reads it except with your explicit permission, to resolve a support issue
            you raised, for security purposes, or where required by law.
          </p>
        </Section>

        <Section title="Who else sees it">
          <p>
            We do not sell your data. We share it only with the providers needed to deliver the
            service:
          </p>
          <ul className="list-disc space-y-1.5 pl-5">
            <li>
              <strong className="text-foreground">AI providers.</strong> To generate a reply, the
              relevant conversation messages and your business knowledge are sent to the AI provider
              configured for your account (such as Google Gemini, OpenAI, or Groq). If voice replies
              are on, audio is sent to a speech provider for transcription and synthesis.
            </li>
            <li>
              <strong className="text-foreground">WhatsApp / Meta.</strong> Message delivery happens
              over WhatsApp and is subject to its own terms and privacy policy.
            </li>
            <li>
              <strong className="text-foreground">Google.</strong> Only when you connect it, and only
              for the calendar and spreadsheet described above.
            </li>
            <li>
              <strong className="text-foreground">Hosting and email.</strong> Our server host and, if
              configured, the email provider used to send you alerts.
            </li>
            <li>
              <strong className="text-foreground">Legal.</strong> Where we are legally required to
              disclose, or to protect our rights or someone&apos;s safety.
            </li>
          </ul>
        </Section>

        <Section title="How we protect it">
          <p>
            Google refresh tokens and other third-party credentials are encrypted at rest with
            Fernet (AES-128-CBC with HMAC authentication) before being written to the database. All
            traffic is served over HTTPS.
          </p>
          <p>
            Every tenant&apos;s data is isolated at the database level with PostgreSQL row-level
            security, enforced by a dedicated application role that cannot bypass it, so one
            business&apos;s conversations, knowledge, and credentials are not reachable from
            another&apos;s session, even in the event of an application bug.
          </p>
          <p>
            No system is perfectly secure, and we cannot guarantee absolute security. If a breach
            affects your data, we will notify you without undue delay.
          </p>
        </Section>

        <Section title="How long we keep it">
          <p>
            Account and business data are kept while your account is active. Conversations and
            operational logs are retained while they are useful for running the service and
            supporting you.
          </p>
          <p>
            When you disconnect Google, we delete the stored refresh token and clear the cached
            access token immediately. Where that grant is not shared with another connected Qonvo
            feature, we also revoke it with Google. Content already written to your calendar or
            spreadsheet stays in your Google account. It is yours, and we do not delete it.
          </p>
          <p>
            When you delete your account, we delete your data within 30 days, except where we must
            retain something to meet a legal obligation.
          </p>
        </Section>

        <Section title="Your choices and rights">
          <p>
            You can view and edit your business data in the dashboard at any time. You may request a
            copy of your data, correction, or deletion by emailing{" "}
            <a href={`mailto:${LEGAL.privacyEmail}`} className="text-primary-strong hover:underline">
              {LEGAL.privacyEmail}
            </a>
            . Depending on where you live, you may also have rights to object to or restrict
            processing, or to complain to a data-protection authority.
          </p>
          <p>
            You can revoke Qonvo&apos;s access to your Google account at any time, either from the{" "}
            <Link href="/integrations" className="text-primary-strong hover:underline">
              Integrations
            </Link>{" "}
            page in Qonvo, or directly at{" "}
            <a
              href="https://myaccount.google.com/permissions"
              target="_blank"
              rel="noreferrer noopener"
              className="text-primary-strong hover:underline"
            >
              myaccount.google.com/permissions
            </a>
            . Revoking stops all Google features immediately; the rest of Qonvo keeps working.
          </p>
        </Section>

        <Section title="Your end customers">
          <p>
            When people message your WhatsApp number, you are the controller of that conversation
            and Qonvo processes it on your behalf. You are responsible for telling your customers
            that an AI assistant may respond and for having a lawful basis to process their
            messages. We will help you honour any access or deletion request they make to you.
          </p>
        </Section>

        <Section title="International transfers and children">
          <p>
            Our providers may process data in countries other than yours, including the United
            States. Qonvo is a business tool and is not directed at children under 16; we do not
            knowingly collect their data.
          </p>
        </Section>

        <Section title="Changes">
          <p>
            We may update this policy as the product changes. We will update the date at the top and,
            for material changes, notify you by email or in the dashboard.
          </p>
        </Section>

        <Section title="Contact">
          <p>
            Questions, requests, or complaints:{" "}
            <a href={`mailto:${LEGAL.privacyEmail}`} className="text-primary-strong hover:underline">
              {LEGAL.privacyEmail}
            </a>
            .
          </p>
        </Section>
      </LegalPage>
    </MarketingShell>
  );
}
