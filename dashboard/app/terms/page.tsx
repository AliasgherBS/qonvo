import type { Metadata } from "next";
import Link from "next/link";

import { LegalPage, MarketingShell, Section } from "@/components/marketing-shell";
import { LEGAL } from "@/lib/legal";
import { trialLengthAdjective } from "@/lib/plan";

export const metadata: Metadata = {
  title: "Terms of Service",
  description: "The terms that govern your use of Qonvo.",
};

export default function TermsPage() {
  return (
    <MarketingShell>
      <LegalPage title="Terms of Service">
        <p className="text-muted-foreground">
          These terms are an agreement between you and {LEGAL.legalEntity} (&ldquo;Qonvo&rdquo;,
          &ldquo;we&rdquo;). By creating an account or using the service, you accept them. If you
          are agreeing on behalf of a business, you confirm you are authorised to do so.
        </p>

        <Section title="1. What Qonvo does">
          <p>
            Qonvo provides an AI assistant that replies to messages sent to your WhatsApp number,
            using the business information you supply. With your permission it can also book
            appointments on a Google Calendar it creates, and record leads and orders to a Google
            spreadsheet you select.
          </p>
        </Section>

        <Section title="2. Your account">
          <p>
            You must give accurate signup details and keep your credentials secure. You are
            responsible for everything that happens under your account. Tell us promptly at{" "}
            <a href={`mailto:${LEGAL.contactEmail}`} className="text-primary-strong hover:underline">
              {LEGAL.contactEmail}
            </a>{" "}
            if you believe it has been compromised. You must be at least 18 years old.
          </p>
        </Section>

        <Section title="3. Free trial and payment">
          <p>
            New accounts include a {trialLengthAdjective} free trial with no card required. After the trial, continued
            use requires a paid plan; if you do not upgrade, your account is restricted and your AI
            rep stops replying. We will tell you the price before charging you, and fees are
            non-refundable except where the law requires otherwise.
          </p>
        </Section>

        <Section title="4. Your content and your customers">
          <p>
            You keep ownership of everything you put into Qonvo: your business information,
            conversations, and any files you connect. You grant us only the licence needed to
            operate the service for you.
          </p>
          <p>
            You are responsible for the lawfulness of the messages Qonvo sends on your behalf. In
            particular, you confirm you have a lawful basis to message the people who contact you,
            that you will tell your customers an AI assistant may reply, and that you will comply
            with WhatsApp&apos;s and Meta&apos;s terms, including their rules on unsolicited and
            bulk messaging.
          </p>
        </Section>

        <Section title="5. Acceptable use">
          <p>You must not use Qonvo to:</p>
          <ul className="list-disc space-y-1.5 pl-5">
            <li>send spam, bulk, or unsolicited broadcast messages;</li>
            <li>impersonate another person or business, or deceive people about who they are dealing with;</li>
            <li>send unlawful, harassing, hateful, or sexually explicit content;</li>
            <li>break the law, infringe someone&apos;s rights, or violate WhatsApp&apos;s or Google&apos;s terms;</li>
            <li>attempt to breach, overload, reverse-engineer, or probe the service or its infrastructure;</li>
            <li>process sensitive personal data such as health records, payment card numbers, or government identifiers.</li>
          </ul>
          <p>
            We may suspend or terminate an account that breaches this section, without notice where
            the breach is serious.
          </p>
        </Section>

        <Section title="6. WhatsApp and third-party services">
          <p>
            Qonvo depends on services we do not control, including WhatsApp, Google, and AI
            providers. We are not responsible for their availability, their decisions, or changes
            they make. In particular, WhatsApp may restrict or ban a number for behaviour that
            breaches its policies. That decision is Meta&apos;s alone, and we cannot reverse it.
            Your use of Google features is additionally subject to Google&apos;s own terms.
          </p>
        </Section>

        <Section title="7. AI output">
          <p>
            Qonvo generates replies automatically and can be wrong, incomplete, or misinterpret a
            question, even when the underlying business information is correct. You are responsible
            for reviewing what it does on your behalf, including bookings, orders and any
            commitment made to a customer, and for taking over a conversation when it matters. Do
            not rely on Qonvo for legal, medical, or financial advice.
          </p>
        </Section>

        <Section title="8. Availability">
          <p>
            We aim to keep Qonvo running but do not promise uninterrupted service. We may change,
            suspend, or discontinue features, and we perform maintenance that can cause downtime.
            While the service is in beta, expect a higher rate of change and occasional disruption.
          </p>
        </Section>

        <Section title="9. Privacy">
          <p>
            Our{" "}
            <Link href="/privacy" className="text-primary-strong hover:underline">
              Privacy Policy
            </Link>{" "}
            explains what we collect and how we handle it, including data accessed through Google
            APIs, and forms part of these terms.
          </p>
        </Section>

        <Section title="10. Cancellation">
          <p>
            You may stop using Qonvo and delete your account at any time. We may terminate or suspend
            your account for breach of these terms, or with reasonable notice for any other reason.
            On termination your access ends and we delete your data as described in the Privacy
            Policy.
          </p>
        </Section>

        <Section title="11. Disclaimers and liability">
          <p>
            To the fullest extent permitted by law, Qonvo is provided &ldquo;as is&rdquo; without
            warranties of any kind, express or implied, including fitness for a particular purpose.
          </p>
          <p>
            We are not liable for indirect, incidental, special, or consequential losses, or for lost
            profits, revenue, data, or business opportunities. Our total liability for any claim
            relating to the service is limited to the amount you paid us in the twelve months before
            the claim arose. Nothing here excludes liability that cannot lawfully be excluded.
          </p>
        </Section>

        <Section title="12. Changes to these terms">
          <p>
            We may update these terms as the product evolves. We will update the date at the top and,
            for material changes, notify you by email or in the dashboard. Continuing to use Qonvo
            after a change means you accept it.
          </p>
        </Section>

        <Section title="13. Governing law">
          <p>
            These terms are governed by the laws of {LEGAL.jurisdiction}, and its courts have
            exclusive jurisdiction over any dispute, without affecting mandatory consumer rights you
            may have where you live.
          </p>
        </Section>

        <Section title="14. Contact">
          <p>
            Questions about these terms:{" "}
            <a href={`mailto:${LEGAL.contactEmail}`} className="text-primary-strong hover:underline">
              {LEGAL.contactEmail}
            </a>
            .
          </p>
        </Section>
      </LegalPage>
    </MarketingShell>
  );
}
