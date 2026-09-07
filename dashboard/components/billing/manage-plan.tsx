"use client";

import { AlertTriangle, CalendarClock, Loader2, RotateCcw } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/ui/toast";
import {
  CANCELLATION_REASONS,
  describeError,
  subscription as subscriptionApi,
  type BillingStatus,
  type CancellationReason,
} from "@/lib/api";
import { useAuthToken } from "@/lib/use-api";

/**
 * Cancel and resume, in the app rather than in the provider's portal.
 *
 * The provider stays the system of record: this calls its API and its webhook
 * writes our row, so the button being here does not create a second opinion
 * about the subscription. What moving it here buys is the part a hosted portal
 * cannot do, which is telling somebody in our own words exactly what happens
 * to their rep and when.
 *
 * Cancellation is always end-of-period. They have paid for the month; taking it
 * away the instant they click is unkind and is what turns a cancellation into a
 * refund request.
 *
 * The reason is optional and does not gate anything. A form that demands one
 * before letting somebody leave is a dark pattern, and the answer it extracts
 * is not worth having.
 */

const SELECT_CLASSES =
  "h-10 w-full rounded-lg border border-border bg-background px-3 text-sm outline-none focus:border-primary";

function formatDate(iso: string | null) {
  if (!iso) return null;
  return new Date(iso).toLocaleDateString(undefined, {
    day: "numeric",
    month: "long",
    year: "numeric",
  });
}

export function ManagePlan({
  status,
  onChanged,
}: {
  status: BillingStatus;
  onChanged: () => void;
}) {
  const token = useAuthToken();
  const { toast } = useToast();
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [reason, setReason] = useState<CancellationReason | "">("");
  const [comment, setComment] = useState("");

  const sub = status.subscription;
  // Nothing to manage on a trial: there is no subscription to end.
  if (!sub || status.plan !== "paid") return null;

  const endsOn = formatDate(sub.currentPeriodEnd);

  async function run(action: () => Promise<{ ok: boolean; reason: string | null }>, done: string) {
    setBusy(true);
    try {
      const result = await action();
      if (!result.ok) {
        toast({
          title: "Could not do that just now",
          description:
            result.reason === "no_subscription"
              ? "There is no active subscription to change."
              : "Our payment provider did not respond. Try again shortly.",
          variant: "error",
        });
        return;
      }
      toast({ title: done, variant: "success" });
      setConfirming(false);
      setReason("");
      setComment("");
      // The provider's webhook is what updates our row, and it lands within a
      // second or two. Refetching immediately usually shows the new state; if
      // it does not, the next poll will.
      onChanged();
    } catch (err) {
      toast({ title: "Could not do that", description: describeError(err), variant: "error" });
    } finally {
      setBusy(false);
    }
  }

  // --- already cancelled: offer the way back ------------------------------- #
  if (sub.cancelAtPeriodEnd) {
    return (
      <div className="rounded-xl border border-warning/40 bg-warning/10 p-4">
        <p className="flex items-center gap-2 text-sm font-bold">
          <CalendarClock className="h-4 w-4 shrink-0 text-warning" />
          Your plan ends {endsOn ? `on ${endsOn}` : "at the end of this period"}
        </p>
        <p className="mt-1 text-xs text-muted-foreground">
          Nothing changes until then. Your rep keeps answering, and you keep every allowance you
          have now. After that date it stops replying and messages simply arrive in your inbox.
        </p>
        <Button
          variant="outline"
          size="sm"
          className="mt-3"
          disabled={busy}
          onClick={() => run(() => subscriptionApi.resume({ token }), "Your plan will continue")}
        >
          {busy ? (
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          ) : (
            <RotateCcw className="mr-2 h-4 w-4" />
          )}
          Keep my plan
        </Button>
      </div>
    );
  }

  // --- active: renewal date, and a way out --------------------------------- #
  if (!confirming) {
    return (
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border p-4">
        <p className="text-xs text-muted-foreground">
          {endsOn ? (
            <>
              Renews on <strong className="text-foreground">{endsOn}</strong>.
            </>
          ) : (
            "Renews automatically."
          )}{" "}
          Cancel any time and keep everything until then.
        </p>
        <button
          onClick={() => setConfirming(true)}
          className="text-xs font-semibold text-muted-foreground underline-offset-2 hover:text-danger hover:underline"
        >
          Cancel plan
        </button>
      </div>
    );
  }

  // --- confirming ----------------------------------------------------------- #
  return (
    <div className="space-y-3 rounded-xl border border-danger/40 bg-danger/5 p-4">
      <p className="flex items-center gap-2 text-sm font-bold">
        <AlertTriangle className="h-4 w-4 shrink-0 text-danger" />
        Cancel your plan?
      </p>
      {/* Stating the date is the whole point of doing this in the app: it turns
          "cancel" from a leap into a decision with a known consequence. */}
      <p className="text-xs text-muted-foreground">
        Your rep keeps answering until{" "}
        <strong className="text-foreground">{endsOn ?? "the end of this period"}</strong>, and you
        keep every allowance until then. After that it stops replying and messages just arrive in
        your inbox for you to answer. You can undo this any time before that date.
      </p>

      <div className="space-y-1.5">
        <Label htmlFor="cancel-reason">Why are you leaving? (optional)</Label>
        <select
          id="cancel-reason"
          className={SELECT_CLASSES}
          value={reason}
          onChange={(e) => setReason(e.target.value as CancellationReason | "")}
        >
          <option value="">Rather not say</option>
          {CANCELLATION_REASONS.map((r) => (
            <option key={r.value} value={r.value}>
              {r.label}
            </option>
          ))}
        </select>
      </div>

      {reason ? (
        <div className="space-y-1.5">
          <Label htmlFor="cancel-comment">Anything else? (optional)</Label>
          <Textarea
            id="cancel-comment"
            rows={2}
            maxLength={500}
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder="It would genuinely help to know."
          />
        </div>
      ) : null}

      <div className="flex flex-wrap gap-2 pt-1">
        <Button
          variant="danger"
          disabled={busy}
          onClick={() =>
            run(
              () =>
                subscriptionApi.cancel(
                  {
                    reason: reason || undefined,
                    comment: comment.trim() || undefined,
                  },
                  { token },
                ),
              "Your plan will end at the end of the period",
            )
          }
        >
          {busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
          Yes, cancel it
        </Button>
        <Button variant="ghost" disabled={busy} onClick={() => setConfirming(false)}>
          Never mind
        </Button>
      </div>
    </div>
  );
}
