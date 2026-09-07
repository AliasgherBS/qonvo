"use client";

import { useCallback, useEffect, useLayoutEffect, useState } from "react";

import { Button } from "@/components/ui/button";

/**
 * A four-step tour over the real UI (spec §8.2).
 *
 * Over the real UI rather than a carousel of screenshots, because the thing
 * worth learning is where the controls are, and a screenshot teaches nothing
 * you can then act on. Each step dims the page, rings one element, and says one
 * sentence about it.
 *
 * Skippable at every step and shown once. "Once" is per browser, not per
 * tenant, so an invited teammate gets their own run, which is what the spec
 * asked for and needs no migration.
 *
 * Targets are found by `data-tour`, and a step whose target is absent is
 * skipped rather than pointing at nothing. That matters because the switch is
 * only rendered for owners, and the sidebar collapses on mobile.
 */

const SEEN_KEY = "qonvo:tour-seen";

type Step = { target: string; title: string; body: string };

const STEPS: Step[] = [
  {
    target: '[data-tour="nav:/inbox"]',
    title: "Every conversation lands here",
    body: "Read what your rep said, and take over any chat by replying yourself.",
  },
  {
    target: '[data-tour="nav:/knowledge"]',
    title: "This is what makes it useful",
    body: "Prices, hours and policies. Your rep answers from what you put here.",
  },
  {
    target: '[data-tour="nav:/behavior"]',
    title: "How it sounds",
    body: "Its persona, the language it replies in, and when to fetch a human.",
  },
  {
    target: '[data-tour="rep-switch"]',
    title: "Your on and off switch",
    body: "Pause it any time. Messages still arrive; you answer them yourself.",
  },
];

function seen(): boolean {
  try {
    return window.localStorage.getItem(SEEN_KEY) === "1";
  } catch {
    // A private window throws here. Not showing the tour is the polite answer:
    // it is a nicety, and nagging is worse than missing it.
    return true;
  }
}

function markSeen() {
  try {
    window.localStorage.setItem(SEEN_KEY, "1");
  } catch {
    /* nothing to remember */
  }
}

/** Clears the flag so a help menu can offer the tour again. */
export function restartProductTour() {
  try {
    window.localStorage.removeItem(SEEN_KEY);
  } catch {
    /* nothing to clear */
  }
}

export function ProductTour() {
  const [index, setIndex] = useState<number | null>(null);
  const [rect, setRect] = useState<DOMRect | null>(null);

  // Deferred to an effect: localStorage during render makes the server and
  // client markup disagree, and React throws the whole tree away.
  useEffect(() => {
    if (seen()) return;
    // One frame of grace so the page it is describing has actually painted.
    const timer = window.setTimeout(() => setIndex(0), 600);
    return () => window.clearTimeout(timer);
  }, []);

  const finish = useCallback(() => {
    setIndex(null);
    markSeen();
  }, []);

  // Find the current target, skipping any step whose element is not on the
  // page. Measured in a layout effect so the ring is never a frame behind.
  useLayoutEffect(() => {
    if (index === null) return;
    if (index >= STEPS.length) {
      finish();
      return;
    }
    const element = document.querySelector(STEPS[index].target);
    if (!element) {
      setIndex(index + 1);
      return;
    }
    element.scrollIntoView({ block: "center", behavior: "smooth" });
    const measure = () => setRect(element.getBoundingClientRect());
    measure();
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    return () => {
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
    };
  }, [index, finish]);

  useEffect(() => {
    if (index === null) return;
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") finish();
      if (event.key === "ArrowRight" || event.key === "Enter") setIndex((i) => (i ?? 0) + 1);
      if (event.key === "ArrowLeft") setIndex((i) => Math.max(0, (i ?? 0) - 1));
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [index, finish]);

  if (index === null || index >= STEPS.length || !rect) return null;

  const step = STEPS[index];
  const PAD = 8;
  // Below the target unless that would fall off the fold, in which case above.
  const below = rect.bottom + 200 < window.innerHeight;
  const cardTop = below ? rect.bottom + PAD + 6 : Math.max(12, rect.top - 200);
  const cardLeft = Math.min(Math.max(12, rect.left), window.innerWidth - 332);

  return (
    <div className="fixed inset-0 z-50" role="dialog" aria-modal="true" aria-label="Product tour">
      {/* Clicking the dim area leaves, which is what people try first. */}
      <div className="absolute inset-0 bg-ink/60" onClick={finish} />

      {/* The ring. Pointer events off so it never intercepts a click, and no
          cutout: dimming everything and ringing one thing reads the same and
          cannot mis-measure. */}
      <div
        className="pointer-events-none absolute rounded-xl ring-2 ring-primary ring-offset-2 ring-offset-ink/0"
        style={{
          top: rect.top - PAD / 2,
          left: rect.left - PAD / 2,
          width: rect.width + PAD,
          height: rect.height + PAD,
          boxShadow: "0 0 0 9999px rgba(8,19,14,0.55)",
        }}
      />

      <div
        className="absolute w-80 rounded-2xl border border-border bg-background p-4 shadow-xl"
        style={{ top: cardTop, left: cardLeft }}
      >
        <p className="text-xs font-bold uppercase tracking-wide text-primary-strong">
          {index + 1} of {STEPS.length}
        </p>
        <p className="mt-1.5 text-sm font-bold">{step.title}</p>
        <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{step.body}</p>

        <div className="mt-4 flex items-center justify-between gap-2">
          <button
            onClick={finish}
            className="text-xs font-semibold text-muted-foreground underline-offset-2 hover:underline"
          >
            Skip
          </button>
          <div className="flex gap-2">
            {index > 0 ? (
              <Button variant="ghost" size="sm" onClick={() => setIndex(index - 1)}>
                Back
              </Button>
            ) : null}
            <Button size="sm" onClick={() => setIndex(index + 1)}>
              {index === STEPS.length - 1 ? "Done" : "Next"}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
