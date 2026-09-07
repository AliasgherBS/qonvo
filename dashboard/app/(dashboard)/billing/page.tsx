"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { UsageMeters } from "@/components/usage-meters";
import { billing, usage as usageApi } from "@/lib/api";
import { CONTACT } from "@/lib/contact";
import { useApi, useAuthToken } from "@/lib/use-api";

/**
 * Plan, entitlements and upgrade. Prices are not published here on purpose:
 * they live with the payment provider, so this page shows what a plan grants
 * and hands off to whatever checkout is configured. With no gateway connected
 * that handoff is a message to us rather than a checkout that does not exist.
 */

const BLOCKED_COPY: Record<string, string> = {
  suspended: "This account is suspended, so your AI rep has stopped replying.",
  trial_expired: "Your trial has ended and your AI rep has paused replying.",
  past_due: "We could not take the last payment, so your AI rep has paused replying.",
  canceled: "This plan has ended and your AI rep has paused replying.",
};

const ENTITLEMENT_LABELS: Record<string, string> = {
  monthly_message_quota: "Messages a month",
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
          <Card>
            <CardHeader>
              <CardTitle className="capitalize">
                {data.subscription?.planKey ?? data.plan} plan
              </CardTitle>
              <CardDescription>
                {data.expired
                  ? (BLOCKED_COPY[data.blockedReason ?? ""] ??
                    "Your AI rep has paused replying.")
                  : data.daysLeft !== null
                    ? `${data.daysLeft} ${data.daysLeft === 1 ? "day" : "days"} left on your trial.`
                    : `Status: ${data.subscription?.status ?? data.status}.`}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {/* Meters rather than a list of allowances. "5,000 messages a
                  month" answers a question nobody asked; "1,240 of 5,000, resets
                  1 Oct" answers the one they did. Falls back to the plain list
                  if the usage call fails, so a slow query never leaves this card
                  blank. */}
              {meters.data ? (
                <UsageMeters usage={meters.data} />
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
              {data.subscription?.currentPeriodEnd ? (
                <p className="text-sm text-muted-foreground">
                  {data.subscription.cancelAtPeriodEnd ? "Ends" : "Renews"} on{" "}
                  {new Date(data.subscription.currentPeriodEnd).toLocaleDateString()}.
                </p>
              ) : null}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Plans</CardTitle>
              <CardDescription>
                We size pricing with you rather than publishing a table, so pick the volume you
                need and we will confirm the cost.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {plans.loading ? (
                <Skeleton className="h-24 w-full" />
              ) : (
                (plans.data ?? [])
                  .filter((plan) => plan.key !== "trial")
                  .map((plan) => {
                    const isCurrent = plan.key === currentKey;
                    return (
                      <div
                        key={plan.key}
                        className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border p-4"
                      >
                        <div>
                          <p className="font-semibold">{plan.name}</p>
                          <p className="text-sm text-muted-foreground">
                            {plan.entitlements.monthly_message_quota?.toLocaleString()} messages a
                            month, {plan.entitlements.seats} team seats
                          </p>
                        </div>
                        <Button
                          variant={isCurrent ? "outline" : "primary"}
                          disabled={isCurrent || pending !== null}
                          onClick={() => upgrade(plan.key)}
                        >
                          {isCurrent
                            ? "Current plan"
                            : pending === plan.key
                              ? "Starting..."
                              : "Choose"}
                        </Button>
                      </div>
                    );
                  })
              )}

              {message ? (
                <div className="rounded-lg border border-border bg-muted/40 p-4 text-sm">
                  <p>{message}</p>
                  <div className="mt-3 flex flex-wrap gap-3">
                    <a
                      href={CONTACT.whatsappHref}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex"
                    >
                      <Button size="sm">Message us on WhatsApp</Button>
                    </a>
                    <a href={CONTACT.emailHref} className="inline-flex">
                      <Button size="sm" variant="outline">
                        Email us
                      </Button>
                    </a>
                  </div>
                </div>
              ) : null}
            </CardContent>
          </Card>
        </>
      ) : null}
    </div>
  );
}
