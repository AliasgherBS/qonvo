"use client";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { CONTACT } from "@/lib/contact";
import type { PlanInfo, TenantUsage } from "@/lib/api";

/**
 * What else the owner could be on, with the four allowances that differ
 * (teardown Z2) and an honest account of what a change costs (teardown Z5).
 *
 * Z2: the rows used to describe a plan by messages and seats only, while the
 * meters above metered voice as well. Voice is the entitlement most likely to
 * make somebody upgrade and the one that costs us most to serve, and it was
 * missing from the exact moment the decision gets made.
 *
 * Z5: proration used to be promised in prose ("you are only charged for what
 * you use") and never shown as a number. Polar publishes no preview endpoint
 * for it -- the change-preview schemas exist in their OpenAPI document and no
 * route returns them -- so there is no figure to show before the change is
 * made. Rather than keep describing a rule as though it were an answer, this
 * says who works the amount out and when it appears.
 *
 * Prices are deliberately absent: they live with the merchant of record.
 */

/** The allowances that differ between plans, in the order they matter. */
const COMPARED: { key: string; singular: string; unit?: string }[] = [
  { key: "monthly_message_quota", singular: "messages a month" },
  { key: "monthly_voice_minutes", singular: "voice minutes a month" },
  { key: "seats", singular: "team seats" },
  { key: "knowledge_sources", singular: "knowledge sources" },
];

/** Which entitlement each meter is a measurement of, so the one under the most
    pressure can be highlighted in every row. */
const METER_TO_ENTITLEMENT: {
  key: string;
  ratio: (u: TenantUsage) => number;
}[] = [
  { key: "monthly_message_quota", ratio: (u) => u.messages.ratio },
  { key: "monthly_voice_minutes", ratio: (u) => u.voiceMinutes.ratio },
  { key: "seats", ratio: (u) => u.seats.ratio },
  { key: "knowledge_sources", ratio: (u) => u.knowledgeSources.ratio },
];

function tightestEntitlement(usage: TenantUsage | null): string | null {
  if (!usage) return null;
  const [worst] = [...METER_TO_ENTITLEMENT].sort((a, b) => b.ratio(usage) - a.ratio(usage));
  // Nothing is under pressure below a fifth used, and highlighting the least
  // idle of six idle meters would be noise dressed as a signal.
  return worst && worst.ratio(usage) >= 0.2 ? worst.key : null;
}

function deltas(plan: PlanInfo, current: Record<string, number>): string[] {
  const out: string[] = [];
  for (const { key, singular } of COMPARED) {
    const mine = current[key] ?? 0;
    const theirs = plan.entitlements[key] ?? 0;
    const diff = theirs - mine;
    if (!diff) continue;
    out.push(`${diff > 0 ? "+" : "-"}${Math.abs(diff).toLocaleString()} ${singular}`);
  }
  return out;
}

export function PlanComparison({
  plans,
  loading,
  currentKey,
  currentEntitlements,
  usage,
  hasSubscription,
  pending,
  message,
  onChoose,
}: {
  plans: PlanInfo[];
  loading: boolean;
  currentKey: string | null;
  currentEntitlements: Record<string, number>;
  usage: TenantUsage | null;
  hasSubscription: boolean;
  pending: string | null;
  message: string | null;
  onChoose: (planKey: string) => void;
}) {
  const tightest = tightestEntitlement(usage);

  return (
    <Card id="plans">
      <CardHeader>
        <div className="space-y-1">
          <CardTitle>Plans</CardTitle>
          <CardDescription>
            Change plan any time. A change takes effect straight away, and our payment provider
            works out the difference for the part of the month you have already paid for. They
            calculate that when the change goes through rather than before it, so the exact figure
            appears on your next invoice below and not on this page.
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {loading ? (
          <Skeleton className="h-24 w-full" />
        ) : (
          plans
            .filter((plan) => plan.key !== "trial")
            .map((plan) => {
              const isCurrent = plan.key === currentKey;
              const delta = isCurrent ? [] : deltas(plan, currentEntitlements);
              return (
                <div
                  key={plan.key}
                  className={`flex flex-wrap items-start justify-between gap-3 rounded-lg border p-4 ${
                    isCurrent ? "border-primary/40 bg-primary/5" : "border-border"
                  }`}
                >
                  <div className="space-y-1">
                    <p className="font-semibold">{plan.name}</p>
                    <ul className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
                      {COMPARED.map(({ key, singular }) => (
                        <li
                          key={key}
                          className={
                            key === tightest
                              ? "font-semibold text-foreground"
                              : "text-muted-foreground"
                          }
                        >
                          {(plan.entitlements[key] ?? 0).toLocaleString()} {singular}
                        </li>
                      ))}
                    </ul>
                    {delta.length ? (
                      <p className="text-xs text-muted-foreground">
                        Against your plan: {delta.join(", ")}
                      </p>
                    ) : null}
                  </div>
                  <Button
                    variant={isCurrent ? "outline" : "primary"}
                    disabled={isCurrent || pending !== null}
                    onClick={() => onChoose(plan.key)}
                  >
                    {isCurrent
                      ? "Current plan"
                      : pending === plan.key
                        ? "Working..."
                        : /* Say which direction it goes. "Choose" on a cheaper
                             plan reads like starting over. */
                          hasSubscription
                          ? (plan.entitlements.monthly_message_quota ?? 0) >
                            (currentEntitlements.monthly_message_quota ?? 0)
                            ? "Upgrade"
                            : "Switch to this"
                          : "Choose"}
                  </Button>
                </div>
              );
            })
        )}

        {tightest ? (
          <p className="text-xs text-muted-foreground">
            The allowance in bold is the one you are closest to using up.
          </p>
        ) : null}

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
  );
}
