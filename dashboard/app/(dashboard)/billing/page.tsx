"use client";

import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { CardOnFile } from "@/components/billing/card-on-file";
import { ManagePlan } from "@/components/billing/manage-plan";
import { PaymentHistory } from "@/components/billing/payment-history";
import { PlanComparison } from "@/components/billing/plan-comparison";
import { UsageZone } from "@/components/billing/usage-zone";
import { billing, subscription as subscriptionApi, usage as usageApi } from "@/lib/api";
import { useApi, useAuthToken } from "@/lib/use-api";

/**
 * Billing, in four zones, because that is the order the questions arrive in
 * (teardown, "Billing, redesigned"): what am I on and when am I next charged;
 * am I near a limit; how am I paying and what have I paid; what else could I
 * be on. It was one card of six meters at a single weight, with the renewal
 * date in grey at the bottom.
 *
 * Prices are still not published here on purpose: they live with the payment
 * provider, so this page shows what a plan grants and hands off to whatever
 * checkout is configured. With no gateway connected that handoff is a message
 * to us rather than a checkout that does not exist.
 */

const BLOCKED_COPY: Record<string, string> = {
  suspended: "This account is suspended, so your AI rep has stopped replying.",
  trial_expired: "Your trial has ended and your AI rep has paused replying.",
  past_due: "We could not take the last payment, so your AI rep has paused replying.",
  canceled: "This plan has ended and your AI rep has paused replying.",
};

const BLOCKED_BADGE: Record<string, string> = {
  suspended: "Suspended",
  trial_expired: "Trial ended",
  past_due: "Payment failed",
  canceled: "Ended",
};

const ENTITLEMENT_LABELS: Record<string, string> = {
  monthly_message_quota: "Messages a month",
  monthly_voice_minutes: "Voice minutes a month",
  seats: "Team seats",
};

export default function BillingPage() {
  const token = useAuthToken();
  const status = useApi(() => billing.get({ token }), [token]);
  const plans = useApi(() => billing.plans({ token }), [token]);
  const meters = useApi(() => usageApi.mine({ token }), [token]);
  const [pending, setPending] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const data = status.data;
  const currentKey = data?.subscription?.planKey ?? (data?.plan === "trial" ? "trial" : null);

  async function upgrade(planKey: string) {
    setPending(planKey);
    setMessage(null);
    try {
      // Already subscribed: change the plan in place. Sending them through
      // checkout again would restart the billing period and charge a full
      // price on the day they downgraded.
      if (data?.subscription) {
        const result = await subscriptionApi.changePlan(planKey, { token });
        if (result.ok) {
          setMessage(
            "Your plan has changed and the new allowances are live already. Our payment " +
              "provider works out the difference for the rest of this month and puts it on " +
              "your next invoice.",
          );
          // The provider's webhook writes our row and rewrites the
          // entitlements, so both of these need refetching.
          status.refetch();
          meters.refetch();
          return;
        }
        setMessage("We could not change the plan just now. Try again shortly.");
        return;
      }

      const checkout = await billing.checkout(planKey, { token });
      if (checkout.url) {
        window.location.href = checkout.url;
        return;
      }
      setMessage(checkout.instructions ?? "Message us and we will switch it over for you.");
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Could not start the upgrade.");
    } finally {
      setPending(null);
    }
  }

  /** Status as form rather than as 12px grey text in a corner: active,
      cancelling, trialling and blocked should be told apart before a word is
      read. */
  function statusBadge() {
    if (!data) return null;
    if (data.expired) {
      return <Badge tone="danger">{BLOCKED_BADGE[data.blockedReason ?? ""] ?? "Paused"}</Badge>;
    }
    if (data.subscription?.cancelAtPeriodEnd) return <Badge tone="warning">Cancelling</Badge>;
    if (data.plan === "trial") return <Badge tone="info">Trial</Badge>;
    return <Badge tone="success">Active</Badge>;
  }

  return (
    <div className="max-w-3xl space-y-6">
      <div>
        <h1 className="text-2xl font-extrabold tracking-tight">Billing</h1>
        <p className="text-sm text-muted-foreground">Your plan, what it includes, and upgrades.</p>
      </div>

      {status.loading ? (
        <Card>
          <CardContent className="space-y-3 pt-5">
            <Skeleton className="h-4 w-1/4" />
            <Skeleton className="h-10 w-1/2" />
          </CardContent>
        </Card>
      ) : status.error && !data ? (
        <Card>
          <CardContent className="pt-5 text-sm text-muted-foreground">
            {status.error}
            <Button variant="outline" size="sm" className="ml-3" onClick={status.refetch}>
              Retry
            </Button>
          </CardContent>
        </Card>
      ) : data ? (
        <>
          {/* --- Zone 1: what am I on, and when am I next charged ---------- */}
          <Card>
            <CardHeader>
              {/* CardHeader lays its children out in a row, so the title, the
                  badge and the sentence go in one column child rather than
                  being flung to opposite ends of the card. */}
              <div className="space-y-1">
                <div className="flex flex-wrap items-center gap-3">
                  <CardTitle className="capitalize">
                    {data.subscription?.planKey ?? data.plan} plan
                  </CardTitle>
                  {statusBadge()}
                </div>
                {/* Only when there is something to say. An unconditional
                  "Status: active" is the grey line the teardown found easy to
                  miss, and the badge above says it better. */}
                {data.expired || data.daysLeft !== null ? (
                  <CardDescription>
                    {data.expired
                      ? (BLOCKED_COPY[data.blockedReason ?? ""] ??
                        "Your AI rep has paused replying.")
                      : `${data.daysLeft} ${data.daysLeft === 1 ? "day" : "days"} left on your trial.`}
                  </CardDescription>
                ) : null}
              </div>
            </CardHeader>
            {/* The renewal date, and a way to change or end the plan. The
                provider stays the system of record: these calls write nothing
                locally, its webhook does.

                Nothing at all for a suspended account: what happens next there
                is not the owner's to change, and the badge has said it. */}
            {data.subscription && data.plan === "paid" ? (
              <CardContent>
                <ManagePlan status={data} onChanged={status.refetch} />
              </CardContent>
            ) : data.plan === "trial" ? (
              <CardContent>
                <p className="text-xs text-muted-foreground">
                  Nothing is being charged yet. Choose a plan below and your rep keeps answering
                  when the trial ends; leave it and it stops replying that day.
                </p>
              </CardContent>
            ) : null}
          </Card>

          {/* --- Zone 2: am I near a limit -------------------------------- */}
          <Card>
            <CardHeader>
              <div className="space-y-1">
                <CardTitle>Usage</CardTitle>
                <CardDescription>Worst first, with what happens if one fills up.</CardDescription>
              </div>
            </CardHeader>
            <CardContent>
              {/* Meters rather than a list of allowances. "5,000 messages a
                  month" answers a question nobody asked; "1,240 of 5,000,
                  resets 1 Oct" answers the one they did. Falls back to the
                  plain list if the usage call fails, so a slow query never
                  leaves this card blank. */}
              {meters.data ? (
                <UsageZone
                  usage={meters.data}
                  renewsOn={data.subscription?.currentPeriodEnd ?? null}
                />
              ) : meters.loading ? (
                <div className="space-y-4">
                  <Skeleton className="h-10 w-full" />
                  <Skeleton className="h-10 w-full" />
                </div>
              ) : (
                <dl className="grid gap-4 sm:grid-cols-2">
                  {Object.entries(data.entitlements).map(([key, value]) => (
                    <div key={key}>
                      <dt className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                        {ENTITLEMENT_LABELS[key] ?? key}
                      </dt>
                      <dd className="mt-1 font-semibold">{value.toLocaleString()}</dd>
                    </div>
                  ))}
                </dl>
              )}
            </CardContent>
          </Card>

          {/* --- Zone 3: how am I paying, and what have I paid ------------- */}
          <CardOnFile />
          <PaymentHistory />

          {/* --- Zone 4: what else could I be on -------------------------- */}
          <PlanComparison
            plans={plans.data ?? []}
            loading={plans.loading}
            currentKey={currentKey}
            currentEntitlements={data.entitlements}
            usage={meters.data ?? null}
            hasSubscription={Boolean(data.subscription)}
            pending={pending}
            message={message}
            onChoose={upgrade}
          />
        </>
      ) : null}
    </div>
  );
}
