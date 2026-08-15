"use client";

import { AlertTriangle, Sparkles } from "lucide-react";

import { billing, type BillingStatus } from "@/lib/api";
import { useAuthToken, usePolling } from "@/lib/use-api";

/**
 * Owner-facing plan/trial indicator. Shows days left during a trial, and a
 * clear "your bot is paused" banner once the trial ends or the tenant is
 * suspended — so trial expiry is never silent. Hidden for paid, active tenants.
 */
export function TrialBanner() {
  const token = useAuthToken();
  const { data } = usePolling<BillingStatus>(() => billing.get({ token }), 300_000, [token]);

  if (!data) return null;
  if (data.plan === "paid" && data.status !== "suspended") return null;

  // Bot is paused: suspended account or an ended trial.
  if (data.status === "suspended" || data.expired) {
    const msg =
      data.status === "suspended"
        ? "Your account is suspended — your AI rep isn't replying. Contact your Qonvo rep to reactivate."
        : "Your free trial has ended — your AI rep has paused replying. Contact your Qonvo rep to go paid.";
    return (
      <div className="mb-4 flex items-center gap-3 rounded-2xl border border-danger/40 bg-danger/10 px-4 py-3 text-sm font-semibold text-foreground">
        <AlertTriangle className="h-4 w-4 shrink-0 text-danger" />
        <span>{msg}</span>
      </div>
    );
  }

  // Active trial: show days left (louder in the last few days).
  if (data.plan === "trial" && data.daysLeft !== null) {
    const soon = data.daysLeft <= 3;
    return (
      <div
        className={
          soon
            ? "mb-4 flex items-center gap-3 rounded-2xl border border-warning/40 bg-warning/10 px-4 py-3 text-sm font-semibold text-foreground"
            : "mb-4 flex items-center gap-3 rounded-2xl border border-border bg-surface px-4 py-3 text-sm text-foreground"
        }
      >
        <Sparkles className="h-4 w-4 shrink-0 text-primary-strong" />
        <span>
          {data.daysLeft === 0
            ? "Your free trial ends today."
            : `${data.daysLeft} day${data.daysLeft === 1 ? "" : "s"} left in your free trial.`}{" "}
          <span className="text-muted-foreground">Contact your Qonvo rep to go paid.</span>
        </span>
      </div>
    );
  }

  return null;
}
