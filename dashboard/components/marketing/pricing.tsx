import { Check } from "lucide-react";
import Link from "next/link";

import { Reveal } from "@/components/marketing/reveal";
import { buttonClasses } from "@/components/ui/button";
import { CONTACT } from "@/lib/contact";
import { trialHeadline } from "@/lib/plan";

/**
 * Three tiers, expanded in place from the single card this was while prices
 * were undecided.
 *
 * Every allowance is stated twice: as the thing an owner is buying, and as the
 * number underneath it. "About 100 conversations a month" is what a salon owner
 * can picture; "1,000 messages" is what the meter counts, and the two have to
 * agree or the first is a lie the billing page exposes.
 *
 * The conversions are deliberately conservative. A conversation is taken as ten
 * messages, and the quota counts both directions -- a customer's three messages
 * and the rep's three replies are six off the meter, not three. Production
 * measures 26 messages per conversation, but that is a demo with heavy
 * back-and-forth; a brisk real enquiry is nearer eight. Ten is the honest
 * middle, and rounding it down is cheaper than being quoted back at us.
 *
 * Voice is stated in spoken replies rather than minutes because nobody buys
 * minutes. Thirty seconds per reply, which is a long WhatsApp voice note.
 *
 * The knowledge allowance is deliberately NOT a number. Two million characters
 * is thirteen hundred pages; stating it invites the reader to wonder whether it
 * is enough, when the truthful answer is that no salon will ever reach it. The
 * ceiling still exists and the billing page still shows it.
 *
 * Prices live here rather than under app/, which is what verify-brand's
 * no-prices gate is protecting: one place to change them, not scattered
 * through pages.
 */
type Tier = {
  name: string;
  price: string;
  cadence: string;
  pitch: string;
  lines: { value: string; detail: string }[];
  cta: string;
  featured?: boolean;
};

const TIERS: Tier[] = [
  {
    name: "Starter",
    price: "$10",
    cadence: "a month",
    pitch: "One number, answered around the clock.",
    lines: [
      { value: "Around 100 conversations", detail: "1,000 messages in and out" },
      { value: "About 120 spoken replies", detail: "60 minutes of voice" },
      { value: "Two people on the inbox", detail: "owner plus one" },
      { value: "One WhatsApp number", detail: "your business line, answered" },
    ],
    cta: "Start free trial",
  },
  {
    name: "Growth",
    price: "$20",
    cadence: "a month",
    pitch: "For a shop that is genuinely busy.",
    lines: [
      { value: "Around 500 conversations", detail: "5,000 messages in and out" },
      { value: "About 360 spoken replies", detail: "180 minutes of voice" },
      { value: "Five people on the inbox", detail: "your whole front desk" },
      { value: "Three times the knowledge", detail: "150 documents, more detail" },
    ],
    cta: "Start free trial",
    featured: true,
  },
  {
    name: "Scale",
    price: "$60",
    cadence: "a month",
    pitch: "More than one branch, or one very busy one.",
    lines: [
      { value: "Around 2,000 conversations", detail: "20,000 messages in and out" },
      { value: "About 960 spoken replies", detail: "480 minutes of voice" },
      { value: "Fifteen people on the inbox", detail: "across branches" },
      { value: "Two WhatsApp numbers", detail: "run two lines from one account" },
    ],
    cta: "Talk to us",
  },
];

const EVERY_PLAN = [
  "Your own WhatsApp number",
  "Replies by text and by voice note",
  "Customers can send voice notes without limit",
  "Upload everything you have: prices, policies, FAQs",
  "Google Calendar booking",
  "Order and lead capture to a Google Sheet",
  "Handover to you, any time",
  "Shared inbox and analytics",
];

export function Pricing() {
  return (
    <section id="pricing" className="border-t border-border/60 bg-surface/40">
      <div className="mx-auto w-full max-w-6xl px-4 py-24 sm:py-32">
        <Reveal>
          <h2 className="text-center text-4xl font-extrabold leading-tight tracking-tight md:text-5xl">
            Start free. Pay when it is working.
          </h2>
        </Reveal>

        <Reveal delay={0.08}>
          <p className="mx-auto mt-5 max-w-2xl text-center text-lg text-muted-foreground">
            Every plan is the whole product. What grows is how many customers it
            can look after, and how much of your business it knows.
          </p>
        </Reveal>

        <div className="mt-12 grid gap-6 lg:grid-cols-3">
          {TIERS.map((tier, i) => (
            <Reveal key={tier.name} delay={0.14 + i * 0.06}>
              <div
                className={`flex h-full flex-col rounded-3xl border bg-surface p-8 ${
                  tier.featured
                    ? "border-primary shadow-lg shadow-primary/10"
                    : "border-border"
                }`}
              >
                {/* Reserved on every card, not only the featured one: without
                    it the badge pushes Growth's price a row lower than the
                    other two, and three prices that do not line up read as a
                    mistake rather than as emphasis. */}
                <div className="mb-4 h-6">
                  {tier.featured ? (
                    <span className="rounded-full bg-primary/15 px-3 py-1 text-xs font-bold text-primary-strong">
                      Most businesses start here
                    </span>
                  ) : null}
                </div>

                <h3 className="text-xl font-extrabold">{tier.name}</h3>
                <p className="mt-1 text-sm text-muted-foreground">{tier.pitch}</p>

                <p className="mt-5 flex items-baseline gap-1.5">
                  <span className="text-4xl font-extrabold tracking-tight">{tier.price}</span>
                  <span className="text-sm text-muted-foreground">{tier.cadence}</span>
                </p>

                <ul className="mt-5 flex-1 space-y-3 border-t border-border pt-5">
                  {tier.lines.map((line) => (
                    <li key={line.value} className="flex items-start gap-2.5">
                      <Check className="mt-0.5 h-5 w-5 shrink-0 text-primary" />
                      <span>
                        <span className="font-semibold">{line.value}</span>
                        {/* The meter's own number, so the promise above can be
                            checked against the billing page rather than taken
                            on trust. */}
                        <span className="block text-sm text-muted-foreground">
                          {line.detail}
                        </span>
                      </span>
                    </li>
                  ))}
                </ul>

                <Link
                  href="/signup"
                  className={`${buttonClasses({
                    size: "lg",
                    variant: tier.featured ? "primary" : "outline",
                  })} mt-7 w-full justify-center`}
                >
                  {tier.cta}
                </Link>
              </div>
            </Reveal>
          ))}
        </div>

        <Reveal delay={0.34}>
          <div className="mt-10 rounded-3xl border border-border bg-surface p-8 sm:p-10">
            <p className="font-bold">On every plan</p>
            <ul className="mt-5 grid gap-3 sm:grid-cols-2">
              {EVERY_PLAN.map((item) => (
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
