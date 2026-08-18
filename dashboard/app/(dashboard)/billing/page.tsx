"use client";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { billing } from "@/lib/api";
import { CONTACT } from "@/lib/contact";
import { useApi, useAuthToken } from "@/lib/use-api";

/**
 * Plan and trial status. There is no self-serve upgrade yet and prices are not
 * published, so this reports state honestly and routes to a person rather than
 * showing a checkout that does not exist.
 */
export default function BillingPage() {
  const token = useAuthToken();
  const { data, loading, error, refetch } = useApi(() => billing.get({ token }), [token]);

  return (
    <div className="max-w-3xl space-y-6">
      <div>
        <h1 className="text-2xl font-extrabold tracking-tight">Billing</h1>
        <p className="text-sm text-muted-foreground">Your plan and trial status.</p>
      </div>

      {loading ? (
        <Card>
          <CardContent className="space-y-3 pt-5">
            <Skeleton className="h-4 w-1/4" />
            <Skeleton className="h-10 w-1/2" />
          </CardContent>
        </Card>
      ) : error && !data ? (
        <Card>
          <CardContent className="pt-5 text-sm text-muted-foreground">
            {error}
            <Button variant="outline" size="sm" className="ml-3" onClick={refetch}>
              Retry
            </Button>
          </CardContent>
        </Card>
      ) : data ? (
        <Card>
          <CardHeader>
            <div>
              <CardTitle className="capitalize">{data.plan} plan</CardTitle>
              <CardDescription>
                {data.expired
                  ? "Your trial has ended and your AI rep has paused replying."
                  : data.daysLeft !== null
                    ? `${data.daysLeft} ${data.daysLeft === 1 ? "day" : "days"} left on your trial.`
                    : `Status: ${data.status}.`}
              </CardDescription>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            <dl className="grid gap-4 sm:grid-cols-2">
              <div>
                <dt className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Plan
                </dt>
                <dd className="mt-1 font-semibold capitalize">{data.plan}</dd>
              </div>
              <div>
                <dt className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Status
                </dt>
                <dd className="mt-1 font-semibold capitalize">{data.status}</dd>
              </div>
            </dl>

            <div className="border-t border-border pt-5">
              <p className="text-sm text-muted-foreground">
                Pricing depends on how many conversations you handle, so we size it with you rather
                than publishing a table. Message us and we will sort it out.
              </p>
              <div className="mt-4 flex flex-wrap gap-3">
                <a
                  href={CONTACT.whatsappHref}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex"
                >
                  <Button>Message us on WhatsApp</Button>
                </a>
                <a href={CONTACT.emailHref} className="inline-flex">
                  <Button variant="outline">Email us</Button>
                </a>
              </div>
            </div>
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}
