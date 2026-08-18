import type { Metadata } from "next";

import { Answered } from "@/components/marketing/answered";
import { Capabilities } from "@/components/marketing/capabilities";
import { ClosingCta } from "@/components/marketing/closing-cta";
import { CostOfWaiting } from "@/components/marketing/cost-of-waiting";
import { Faq } from "@/components/marketing/faq";
import { Hero } from "@/components/marketing/hero";
import { HowItWorks } from "@/components/marketing/how-it-works";
import { Languages } from "@/components/marketing/languages";
import { Pricing } from "@/components/marketing/pricing";
import { StructuredData } from "@/components/marketing/structured-data";
import { Voice } from "@/components/marketing/voice";
import { MarketingShell } from "@/components/marketing-shell";
import { SITE } from "@/lib/site";

export const metadata: Metadata = {
  title: "Qonvo: an AI customer rep on your WhatsApp",
  description: SITE.description,
  alternates: { canonical: "/" },
};

/**
 * The landing page is locked dark, regardless of the user's theme toggle.
 *
 * Three reasons, in order of weight. The hero video's background is Ink, so on
 * a Paper page it reads as a dark rectangle pasted into the layout and on an
 * Ink page it blends invisibly. The brand kit's "on dark" guidance is the
 * explicit one: Signal Green for actions, Volt for the loudest CTA, keep the
 * rest calm. And a page may not flip theme between sections, so a light page
 * with three dark sections would break that rule three times over; a dark page
 * with one light block (Languages) spends the single permitted switch, which
 * is exactly what the promo video does at that same beat.
 *
 * The `dark` class activates the @custom-variant in globals.css. /privacy and
 * /terms are outside this wrapper and keep following the toggle.
 */
export default function HomePage() {
  return (
    <div className="dark bg-background text-foreground">
      <StructuredData />
      <MarketingShell>
        <Hero />
        <CostOfWaiting />
        <Answered />
        <Capabilities />
        <Voice />
        <Languages />
        <HowItWorks />
        <Pricing />
        <Faq />
        <ClosingCta />
      </MarketingShell>
    </div>
  );
}
