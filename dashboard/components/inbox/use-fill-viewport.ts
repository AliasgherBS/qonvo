"use client";

import { useEffect, useRef, useState } from "react";

/**
 * The pixel height that makes an element end at the bottom of the viewport.
 *
 * The inbox is written as a fixed-height application shell, but the ancestor
 * chain only sets `min-h-screen`, so `h-full` never resolved: the panes grew
 * past the window and the composer sat at y=884 in a 900px viewport, reachable
 * only by scrolling the whole page (teardown I2). The obvious fix is a definite
 * height on the shell, and the shell is a layout shared by thirteen other
 * pages, so the height is measured here instead of changed there.
 *
 * Measured rather than expressed in `dvh` arithmetic because what sits above
 * the panes is not a constant: the trial banner, the unverified-email banner,
 * the rep switch and the onboarding checklist each appear only sometimes, and
 * each of them appears *after* its own fetch resolves.
 */
export function useFillViewport(minHeight = 260) {
  const ref = useRef<HTMLDivElement | null>(null);
  const [height, setHeight] = useState<number | null>(null);

  useEffect(() => {
    const element = ref.current;
    if (!element) return;

    const measure = () => {
      // Walked through offsetParent rather than getBoundingClientRect(), so the
      // answer is the element's layout position and does not change while the
      // page is scrolled (which would make the pane resize as you scroll).
      let top = 0;
      for (let node: HTMLElement | null = element; node; node = node.offsetParent as HTMLElement | null) {
        top += node.offsetTop;
      }
      // What the dashboard shell reserves below the content: 2rem of padding on
      // desktop, 7rem on mobile where the fixed bottom bar sits over the page.
      const bottomGap = window.innerWidth >= 1024 ? 32 : 112;
      // The floor is a last resort, and it is why this was still broken after
      // the first attempt: with 698px above the panes it clamped to 380, and
      // 698 + 380 overflows a 900px window, so the composer went back below the
      // fold. A floor that low means the page scrolls only when the viewport is
      // genuinely too short for a two-line transcript, rather than whenever
      // anything is showing above.
      const next = Math.max(minHeight, Math.round(window.innerHeight - top - bottomGap));
      // Only a real change is committed: the observer below fires on every
      // layout, and writing an identical value each time would loop.
      setHeight((prev) => (prev !== null && Math.abs(prev - next) < 2 ? prev : next));
    };

    measure();
    window.addEventListener("resize", measure);
    const observer = new ResizeObserver(measure);
    observer.observe(document.body);
    return () => {
      window.removeEventListener("resize", measure);
      observer.disconnect();
    };
  }, [minHeight]);

  return { ref, height };
}
