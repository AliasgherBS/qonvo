"use client";

import { ArrowRight, CheckCircle2, Circle, Rocket, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { onboarding } from "@/lib/api";
import { useApi, useAuthToken } from "@/lib/use-api";

/**
 * The "get to live" checklist (spec §8.1).
 *
 * Every item is derived server-side from real data, so nothing here can claim
 * a step is done that is not. A checklist with its own stored progress drifts
 * from reality the first time somebody deletes a knowledge source.
 *
 * Each item is a link, because a list that tells you what is missing without
 * taking you there is a list of chores. The last one is activation, which is
 * the same switch §3 put in the layout: onboarding and going live are one
 * journey, and two surfaces both claiming to be the final step is how an owner
 * finishes the checklist and still has a silent rep.
 *
 * Dismissible, and never lost. It hides itself for good once every required
 * step is done; before then, dismissing is remembered per browser and the
 * "Setup" link in the sidebar brings it back.
 */

const DISMISS_KEY = "qonvo:onboarding-dismissed";

/**
 * Per browser rather than per account, deliberately. A newly invited teammate
 * gets their own copy, which is the behaviour the spec asked for, and it needs
 * no column and no migration. The trade-off is honest: clearing site data
 * brings it back, which for a dismissed checklist is the harmless direction to
 * be wrong in.
 */
function readDismissed(): boolean {
  try {
    return window.localStorage.getItem(DISMISS_KEY) === "1";
  } catch {
    // Private windows and blocked site data both throw here. Showing the
    // checklist is the safe answer.
    return false;
  }
}

export function OnboardingChecklist() {
  const token = useAuthToken();
  const { data } = useApi(() => onboarding.get({ token }), [token]);
  // Starts false and is read in an effect: reading localStorage during render
  // makes the server and client markup disagree, which React discards.
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    setDismissed(readDismissed());
  }, []);

  function dismiss() {
    setDismissed(true);
    try {
      window.localStorage.setItem(DISMISS_KEY, "1");
    } catch {
      // Dismissed for this page view only. Better than an error.
    }
  }

  if (!data || data.complete || dismissed) return null;

  const next = data.steps.find((s) => s.required && !s.done);

  return (
    <Card className="border-primary/30 bg-primary/5">
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-2">
            <Rocket className="h-5 w-5 shrink-0 text-primary" />
            <div>
              <CardTitle>Finish setting up</CardTitle>
              <CardDescription>
                {data.doneCount} of {data.totalCount} done.
                {next ? ` Next: ${next.label.toLowerCase()}.` : ""}
              </CardDescription>
            </div>
          </div>
          <button
            onClick={dismiss}
            aria-label="Hide the setup checklist"
            className="rounded-lg p-1 text-muted-foreground transition hover:bg-border hover:text-foreground"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Progress as a bar as well as a count: "2 of 5" is a fact, a bar is
            a feeling, and the feeling is what gets someone to step three. */}
        <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-border">
          <div
            className="h-full rounded-full bg-primary transition-all"
            style={{ width: `${Math.round((data.doneCount / data.totalCount) * 100)}%` }}
          />
        </div>
      </CardHeader>

      <CardContent className="space-y-1">
        {data.steps.map((step) => (
          <Link
            key={step.key}
            href={step.href}
            className="group flex items-start gap-3 rounded-lg px-2 py-2 transition hover:bg-primary/10"
          >
            {step.done ? (
              <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-success" />
            ) : (
              <Circle className="mt-0.5 h-5 w-5 shrink-0 text-muted-foreground" />
            )}
            <div className="min-w-0 flex-1">
              <p
                className={`flex items-center gap-1.5 text-sm font-semibold ${
                  step.done ? "text-muted-foreground line-through" : ""
                }`}
              >
                {step.label}
                {!step.required ? (
                  <span className="text-xs font-normal text-muted-foreground">(optional)</span>
                ) : null}
                {!step.done ? (
                  <ArrowRight className="h-3.5 w-3.5 opacity-0 transition group-hover:opacity-70" />
                ) : null}
              </p>
              {!step.done ? (
                <p className="text-xs text-muted-foreground">{step.description}</p>
              ) : null}
            </div>
          </Link>
        ))}
      </CardContent>
    </Card>
  );
}

/** Clears the dismissal, so a "Setup" entry can bring the checklist back. */
export function restoreOnboardingChecklist() {
  try {
    window.localStorage.removeItem(DISMISS_KEY);
  } catch {
    // Nothing to restore if storage is unavailable.
  }
}
