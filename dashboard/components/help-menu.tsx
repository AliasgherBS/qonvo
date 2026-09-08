"use client";

import { HelpCircle } from "lucide-react";
import { useState } from "react";

import { restoreOnboardingChecklist } from "@/components/onboarding-checklist";
import { restartProductTour } from "@/components/product-tour";
import { onboarding } from "@/lib/api";
import { CONTACT } from "@/lib/contact";
import { useApi, useAuthToken } from "@/lib/use-api";

/**
 * The way back to the guided bits, and the one link to a human (S5, V7).
 *
 * The checklist can be dismissed and the tour runs once, which is the right
 * default and would otherwise make both one-way doors. "Never lose it
 * permanently" is the spec's phrasing, and this is the smallest thing that
 * honours it.
 *
 * Both flags live in localStorage, so clearing them needs a fresh document to
 * take effect: the components read their flag once, in an effect, rather than
 * subscribing to storage. `router.refresh()` is not enough, since that
 * re-renders without remounting.
 *
 * Two dead spots fixed here.
 *
 * The checklist item did nothing once setup was complete, and said nothing
 * either way: `OnboardingChecklist` returns null when every required step is
 * done, so clearing the dismissal reloaded the page and produced no visible
 * change at all. It now reads the same server-derived status the checklist
 * does and says "You are all set" instead of pretending to act.
 *
 * And the checklist only renders on the inbox, so restoring it from any other
 * page reloaded *that* page and showed nothing. The restore navigates to the
 * inbox rather than reloading in place, so the thing the menu item promises is
 * on screen when the navigation finishes.
 */
export function HelpMenu() {
  const token = useAuthToken();
  const [open, setOpen] = useState(false);
  // A cross-tenant admin has no tenant, so this 403s for them and `data` stays
  // null. Unknown is treated as "not complete", which leaves the item working
  // rather than disabling it on a failed read.
  const { data } = useApi(() => onboarding.get({ token }), [token]);
  const setupComplete = data?.complete === true;

  /**
   * `destination` when the thing being restored lives on a specific page, so
   * the reload is also the navigation to it. A full document load either way,
   * deliberately: cheap, happens once, and avoids wiring a storage
   * subscription into two components for a button nobody presses twice.
   */
  function replay(action: () => void, destination?: string) {
    action();
    setOpen(false);
    if (destination) window.location.href = destination;
    else window.location.reload();
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
        <div className="absolute bottom-8 left-3 z-20 w-56 rounded-xl border border-border bg-background p-1 shadow-lg">
          {setupComplete ? (
            <p className="px-3 py-2 text-xs font-semibold text-muted-foreground">
              Setup checklist: you are all set
            </p>
          ) : (
            <button
              onClick={() => replay(restoreOnboardingChecklist, "/inbox")}
              className="w-full rounded-lg px-3 py-2 text-left text-xs font-semibold transition hover:bg-surface-muted"
            >
              Show the setup checklist
            </button>
          )}
          <button
            onClick={() => replay(restartProductTour)}
            className="w-full rounded-lg px-3 py-2 text-left text-xs font-semibold transition hover:bg-surface-muted"
          >
            Replay the tour
          </button>
          {/* The teardown found "contact support" named in the product with no
              address anywhere and no help destination in the navigation. This
              is the destination. */}
          <a
            href={CONTACT.supportHref}
            className="block rounded-lg px-3 py-2 text-left text-xs font-semibold transition hover:bg-surface-muted"
          >
            Email {CONTACT.support}
          </a>
        </div>
      ) : null}
    </div>
  );
}
