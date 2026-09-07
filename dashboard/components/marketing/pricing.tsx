import { Check } from "lucide-react";
import Link from "next/link";

import { Reveal } from "@/components/marketing/reveal";
import { buttonClasses } from "@/components/ui/button";
import { CONTACT } from "@/lib/contact";
import { trialHeadline } from "@/lib/plan";

/**
 * No figures. Pricing is not decided, and three empty tiers read as broken, so
 * this is one card rather than a tier comparison. When prices are settled it
 * expands into tiers in place without the section moving.
 *
 * Included list covers shipped features only.
 */
const INCLUDED = [
  "Your own WhatsApp number",
  "Unlimited knowledge about your business",
  "Replies by text and by voice note",
  "Google Calendar booking",
  "Order and lead capture to a Google Sheet",
  "Handover to you, any time",
  "Shared inbox and analytics",
];

export function Pricing() {
  return (
    <section id="pricing" className="border-t border-border/60 bg-surface/40">
      <div className="mx-auto w-full max-w-4xl px-4 py-24 sm:py-32">
        <Reveal>
          <h2 className="text-center text-4xl font-extrabold leading-tight tracking-tight md:text-5xl">
            Start free. Pay when it is working.
          </h2>
        </Reveal>

        <Reveal delay={0.08}>
          <p className="mx-auto mt-5 max-w-xl text-center text-lg text-muted-foreground">
            Every plan includes the whole product. What you pay depends on how
            many conversations you handle, so talk to us and we will size it
            with you.
          </p>
        </Reveal>

        <Reveal delay={0.14}>
          <div className="mt-12 rounded-3xl border border-border bg-surface p-8 sm:p-10">
            <ul className="grid gap-3 sm:grid-cols-2">
              {INCLUDED.map((item) => (
                <li key={item} className="flex items-start gap-2.5">
                  <Check className="mt-0.5 h-5 w-5 shrink-0 text-primary" />
                  <span className="text-muted-foreground">{item}</span>
                </li>
              ))}
            </ul>

            <div className="mt-9 border-t border-border pt-8">
              <p className="font-bold">{trialHeadline}</p>

              <div className="mt-5 flex flex-wrap items-center gap-3">
                <Link href="/signup" className={buttonClasses({ size: "lg" })}>
                  Start free trial
                </Link>
                <a
                  href={CONTACT.whatsappHref}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={buttonClasses({ variant: "outline", size: "lg" })}
                >
                  Message us on WhatsApp
                </a>
              </div>

              {/*
                The number is answered by Qonvo itself, running our own
                knowledge base. Saying so turns a support link into a live
                demo, so the copy leads with it instead of hiding it.
              */}
              <p className="mt-4 text-sm text-muted-foreground">
                You will be talking to Qonvo. That is rather the point. Prefer a
                human? Email{" "}
                <a href={CONTACT.emailHref} className="underline hover:text-foreground">
                  {CONTACT.email}
                </a>
                .
              </p>
            </div>
          </div>
        </Reveal>
      </div>
    </section>
  );
}
