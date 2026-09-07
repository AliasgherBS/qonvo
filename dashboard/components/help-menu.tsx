"use client";

import { HelpCircle } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { restoreOnboardingChecklist } from "@/components/onboarding-checklist";
import { restartProductTour } from "@/components/product-tour";

/**
 * The way back to the guided bits.
 *
 * The checklist can be dismissed and the tour runs once, which is the right
 * default and would otherwise make both one-way doors. "Never lose it
 * permanently" is the spec's phrasing, and this is the smallest thing that
 * honours it.
 *
 * Both flags live in localStorage, so clearing them needs a reload to take
 * effect: the components read their flag once, in an effect, rather than
 * subscribing to storage. `router.refresh()` is not enough, since that
 * re-renders without remounting.
 */
export function HelpMenu() {
  const router = useRouter();
  const [open, setOpen] = useState(false);

  function replay(action: () => void) {
    action();
    setOpen(false);
    // A full reload, deliberately. Cheap, happens once, and avoids wiring a
    // storage subscription into two components for a button nobody presses
    // twice.
    window.location.reload();
    router.refresh();
  }

  return (
    <div className="relative px-3">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-2 text-xs font-semibold text-muted-foreground transition hover:text-foreground"
        aria-expanded={open}
      >
        <HelpCircle className="h-3.5 w-3.5" />
        Show me around
      </button>

      {open ? (
        <div className="absolute bottom-8 left-3 z-20 w-52 rounded-xl border border-border bg-background p-1 shadow-lg">
          <button
            onClick={() => replay(restoreOnboardingChecklist)}
            className="w-full rounded-lg px-3 py-2 text-left text-xs font-semibold transition hover:bg-surface-muted"
          >
            Show the setup checklist
          </button>
          <button
            onClick={() => replay(restartProductTour)}
            className="w-full rounded-lg px-3 py-2 text-left text-xs font-semibold transition hover:bg-surface-muted"
          >
            Replay the tour
          </button>
        </div>
      ) : null}
    </div>
  );
}
