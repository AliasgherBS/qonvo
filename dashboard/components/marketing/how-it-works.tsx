"use client";

import { useEffect, useRef, useState } from "react";

import { Reveal } from "@/components/marketing/reveal";

/**
 * The sticky stack, built the way the spec asked for and not the way that
 * costs a screen of scroll per step.
 *
 * No "Step 1 / Step 2 / Step 3" labels: the step content is the label, and the
 * markup is an ordered list so the order is carried by semantics rather than
 * by the numerals, which are decorative and hidden from assistive tech.
 *
 * The heading column is pinned for the whole section (`lg:sticky`), which is
 * also the L4 fix: the heading used to run full width with the steps stacked
 * beneath it, leaving the right half of a desktop viewport empty and making
 * this the third consecutive section with that silhouette.
 *
 * As the reader scrolls, one step at a time is foregrounded and the rest
 * recede to 45 percent: the numeral fills with Signal Green, the rule above it
 * fills behind it so the column reads as a track being walked down, and three
 * ticks under the pinned heading advance with it. That last piece is why the
 * pin earns its keep: a column that is merely stuck reads as a layout
 * accident, and one that responds reads as deliberate.
 *
 * Decisions taken on the owner's behalf, since these were open questions:
 *
 * - Steps flow, they are not pinned and cross-faded. A true pin-and-scrub
 *   spends a viewport per step, which on a page the teardown already calls
 *   7,614 pixels tall is the wrong thing to spend. Each step instead gets a
 *   `clamp(13rem, 30vh, 19rem)` box: enough scroll for the activation band to
 *   hold one step at a time, and short enough that all three stay on screen
 *   together at a laptop height, so the emphasis walks down a list the reader
 *   can already see rather than hiding two thirds of it. Measured cost at
 *   1440x900: the section goes 575px to 903px and the page 7,061 to 7,389, so
 *   4.6 percent taller. At 390x844 it is 2.7 percent.
 * - IntersectionObserver, not `animation-timeline: view()`. The CSS version
 *   needs no JavaScript and was tempting, but Safari still does not ship it,
 *   which is most of an iPhone-first audience, and it animates each element
 *   against its own progress rather than giving one step the floor.
 * - No `Reveal` on the steps any more. The scrub is the entrance motion; a
 *   rise-in underneath a brightness change is two motions doing one job, and
 *   dropping the motion wrapper is what allows the list to be a real `<ol>`.
 *
 * Fallbacks, all of which land on the same place: the plain numbered list at
 * full strength, nothing dimmed and nothing hidden. `active` starts as null
 * and only leaves null when the observer says so, so a reader who asked for
 * reduced motion, a browser with no IntersectionObserver, and a page with no
 * JavaScript at all each keep the static list. Server and first client render
 * are identical, which is the other reason the null state exists: branching
 * markup on a media query is React error #418 (see the note in reveal.tsx).
 *
 * `id` is the target of the header's "How it works" anchor (teardown L3).
 */
const STEPS = [
  {
    title: "Connect WhatsApp",
    body: "Scan one QR code with the number you already give customers.",
  },
  {
    title: "Teach it your business",
    body: "Paste in your hours, prices and the questions you answer most days.",
  },
  {
    title: "Let it answer",
    body: "Send it a test message, then let it work while you get on with the job.",
  },
];

type StepState = "static" | "done" | "active" | "ahead";

export function HowItWorks() {
  const [active, setActive] = useState<number | null>(null);
  const listRef = useRef<HTMLOListElement>(null);

  useEffect(() => {
    const list = listRef.current;
    if (!list) return;
    if (typeof IntersectionObserver === "undefined") return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          setActive(Number((entry.target as HTMLElement).dataset.step));
        }
      },
      // A band across the middle tenth of the viewport. The step boxes tile,
      // so at most two of them can touch the band at once and the one that
      // just entered it is the one the reader is arriving at, going either
      // way. Nothing resets on the way out: leaving the section keeps the last
      // step lit rather than flashing everything back to full strength.
      { rootMargin: "-45% 0px -45% 0px", threshold: 0 },
    );
    for (const step of Array.from(list.querySelectorAll("[data-step]"))) {
      observer.observe(step);
    }
    return () => observer.disconnect();
  }, []);

  const stateOf = (i: number): StepState =>
    active === null
      ? "static"
      : i === active
        ? "active"
        : i < active
          ? "done"
          : "ahead";

  return (
    <section id="how-it-works" className="border-t border-border/60">
      <div className="mx-auto grid w-full max-w-7xl gap-12 px-4 py-24 sm:py-32 lg:grid-cols-[0.85fr_1.15fr] lg:gap-20">
        {/*
          The sticky wrapper is a plain div rather than the Reveal itself:
          Reveal is a motion element and stacking a transform onto a sticky
          element is a class of bug not worth inviting.
        */}
        <div className="lg:sticky lg:top-16 lg:self-start">
          <Reveal>
            <h2 className="text-4xl font-extrabold leading-tight tracking-tight md:text-5xl">
              Live in a day. <span className="text-primary">No code.</span>
            </h2>
            <p className="mt-5 max-w-sm text-lg text-muted-foreground">
              No new number for you, and nothing for your customers to install.
            </p>
            <div className="mt-8 flex gap-2" aria-hidden="true">
              {STEPS.map((step, i) => (
                <span
                  key={step.title}
                  data-state={stateOf(i)}
                  className="h-0.5 w-8 bg-border transition-colors duration-500 data-[state=active]:bg-primary data-[state=done]:bg-primary/40"
                />
              ))}
            </div>
          </Reveal>
        </div>

        <ol ref={listRef} className="max-w-2xl">
          {STEPS.map(({ title, body }, i) => (
            <li
              key={title}
              data-step={i}
              data-state={stateOf(i)}
              className="group/step flex min-h-[clamp(13rem,30vh,19rem)] gap-7 last:min-h-0"
            >
              <div className="flex flex-col items-center" aria-hidden="true">
                <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full border border-primary/40 font-mono text-sm font-bold text-primary transition-colors duration-500 group-data-[state=active]/step:border-primary group-data-[state=active]/step:bg-primary group-data-[state=active]/step:text-primary-foreground group-data-[state=ahead]/step:border-border group-data-[state=ahead]/step:text-muted-foreground">
                  {i + 1}
                </span>
                {i < STEPS.length - 1 ? (
                  <span className="mt-3 w-px flex-1 bg-border transition-colors duration-500 group-data-[state=done]/step:bg-primary/40" />
                ) : null}
              </div>
              <div className="pt-2 transition-opacity duration-500 ease-out group-data-[state=done]/step:opacity-45 group-data-[state=ahead]/step:opacity-45 motion-reduce:transition-none">
                <h3 className="text-2xl font-bold tracking-tight">{title}</h3>
                <p className="mt-2.5 max-w-lg text-lg text-muted-foreground">
                  {body}
                </p>
              </div>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}
