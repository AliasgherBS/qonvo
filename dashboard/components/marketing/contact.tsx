import { Mail, MessageCircle } from "lucide-react";

import { Reveal } from "@/components/marketing/reveal";
import { buttonClasses } from "@/components/ui/button";
import { CONTACT } from "@/lib/contact";

/**
 * Contact as its own section, and its own entry in the header.
 *
 * It existed before only as a footnote under the pricing cards, which put it
 * behind a scroll past three tiers and made it read as "how to ask about
 * pricing" rather than "how to reach us". A visitor who wants to talk to
 * somebody before reading prices had nowhere to go, and the header offered
 * How it works, Pricing and FAQ but no way to ask a question.
 *
 * Positioned after the FAQ deliberately: that is the beat where somebody with
 * an unanswered question is actually standing. The pricing band keeps its own
 * WhatsApp button, because a visitor deciding between tiers should not have to
 * navigate to ask.
 *
 * The WhatsApp number is answered by Qonvo itself, running the product with
 * our own knowledge loaded. The copy leads with that rather than hiding it:
 * the strongest thing this section can do is be the demo.
 *
 * Every address and number comes from lib/contact.ts, which `verify:brand`
 * enforces as the only place they may appear.
 */
export function Contact() {
  return (
    <section id="contact" className="border-t border-border/60">
      <div className="mx-auto w-full max-w-5xl px-4 py-24 sm:py-32">
        <div className="text-center">
          <Reveal>
            <p className="text-xs font-bold uppercase tracking-[0.2em] text-primary">
              Contact us
            </p>
          </Reveal>

          <Reveal delay={0.08}>
            <h2 className="mt-4 text-4xl font-extrabold leading-tight tracking-tight md:text-5xl">
              Ask us anything.
            </h2>
          </Reveal>

          <Reveal delay={0.14}>
            <p className="mx-auto mt-5 max-w-xl text-lg leading-relaxed text-muted-foreground">
              Not sure it fits your business? Tell us what you sell and what you
              get asked all day, and we will tell you straight.
            </p>
          </Reveal>
        </div>

        <div className="mt-12 grid gap-5 md:grid-cols-2">
          <Reveal delay={0.2}>
            <div className="flex h-full flex-col rounded-3xl border border-border bg-surface p-8">
              <MessageCircle className="h-6 w-6 text-primary" aria-hidden="true" />
              <p className="mt-4 text-lg font-bold">Message us on WhatsApp</p>
              <p className="mt-2 flex-1 text-muted-foreground">
                Fastest, and you get to try the product while you do it. The
                number is answered by Qonvo. That is rather the point.
              </p>
              <a
                href={CONTACT.whatsappHref}
                target="_blank"
                rel="noopener noreferrer"
                className={`${buttonClasses({ size: "lg" })} mt-6 w-full justify-center`}
              >
                {CONTACT.whatsapp}
              </a>
            </div>
          </Reveal>

          <Reveal delay={0.26}>
            <div className="flex h-full flex-col rounded-3xl border border-border bg-surface p-8">
              <Mail className="h-6 w-6 text-primary" aria-hidden="true" />
              <p className="mt-4 text-lg font-bold">Email a human</p>
              <p className="mt-2 flex-1 text-muted-foreground">
                For anything longer, or if you would rather not start with a
                bot. We read every one and reply ourselves.
              </p>
              <a
                href={CONTACT.emailHref}
                className={`${buttonClasses({ variant: "outline", size: "lg" })} mt-6 w-full justify-center`}
              >
                {CONTACT.email}
              </a>
            </div>
          </Reveal>
        </div>

        {/* Existing customers are a different question with a different queue,
            and sending them through the sales channel makes both slower. */}
        <Reveal delay={0.32}>
          <p className="mt-8 text-center text-sm text-muted-foreground">
            Already using Qonvo and something is wrong? Email{" "}
            <a href={CONTACT.supportHref} className="underline hover:text-foreground">
              {CONTACT.support}
            </a>{" "}
            and it goes straight to support.
          </p>
        </Reveal>
      </div>
    </section>
  );
}
