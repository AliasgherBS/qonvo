import Link from "next/link";

import { Reveal } from "@/components/marketing/reveal";
import { buttonClasses } from "@/components/ui/button";

/**
 * Repeats the hero headline as a bookend. That is a composition choice, not a
 * duplicate CTA: there is one signup label on the page and this is it again.
 *
 * The Volt accent appears here and nowhere else. The brand kit calls it "a
 * spotlight, not a background", so the loudest CTA on the page gets it and
 * every other action stays Signal Green.
 */
export function ClosingCta() {
  return (
    <section className="border-t border-border/60">
      <div className="mx-auto w-full max-w-7xl px-4 py-28 text-center sm:py-36">
        <Reveal>
          <h2 className="mx-auto max-w-3xl text-5xl font-extrabold leading-[1.05] tracking-tight md:text-6xl">
            Never miss a customer{" "}
            <span className="text-primary">again.</span>
          </h2>
        </Reveal>

        <Reveal delay={0.1}>
          <div className="mt-10 flex justify-center">
            <Link
              href="/signup"
              className={buttonClasses({ variant: "accent", size: "lg" })}
            >
              Start free trial
            </Link>
          </div>
        </Reveal>

        <Reveal delay={0.16}>
          <p className="mt-5 text-sm text-muted-foreground">
            Live in a day. No code.
          </p>
        </Reveal>
      </div>
    </section>
  );
}
