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

/**
 * The allowances that differ between plans, in the order they matter.
 *
 * Two phrasings, because they are read in two places. `label` heads a column
 * and is scanned; `singular` sits mid-sentence in the delta line and has to
 * survive being read as prose.
 */
const COMPARED: { key: string; label: string; singular: string }[] = [
  { key: "monthly_message_quota", label: "Messages a month", singular: "messages a month" },
  { key: "monthly_voice_minutes", label: "Voice minutes a month", singular: "voice minutes a month" },
  { key: "seats", label: "Team seats", singular: "team seats" },
  { key: "knowledge_sources", label: "Knowledge sources", singular: "knowledge sources" },
];

/** Which entitlement each meter is a measurement of, so the one under the most
    pressure can be highlighted in every row. */
const METER_TO_ENTITLEMENT: {
  key: string;
  ratio: (u: TenantUsage) => number;
}[] = [
  { key: "monthly_message_quota", ratio: (u) => u.messages.ratio },
  { key: "monthly_voice_minutes", ratio: (u) => u.voiceMinutes.ratio },
  {
    key: "seats",
    // Measured against the seats the owner can CHOOSE to fill, not against
    // all of them. An owner occupies a seat by existing, so the raw ratio is
    // 50% on a two-seat plan from the first minute of the first day -- and
    // since nothing else is above 20% on a new tenant, "the allowance you are
    // closest to using up" pointed at team seats for every tenant alive,
    // over allowances they had spent literally none of.
    //
    // 1 of 2 is 0% by this measure and 2 of 2 is still 100%, so a genuinely
    // full team is still called out.
    ratio: (u) =>
      u.seats.allowed > 1
        ? Math.max(0, u.seats.used - 1) / (u.seats.allowed - 1)
        : u.seats.ratio,
  },
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
        {tightest && !loading ? (
          <p className="text-xs text-muted-foreground">
            Highlighted in each plan is the allowance you are closest to using up.
          </p>
        ) : null}

        {loading ? (
          <Skeleton className="h-24 w-full" />
        ) : (
          plans
            .filter((plan) => plan.key !== "trial")
            .map((plan) => {
              const isCurrent = plan.key === currentKey;
              const delta = isCurrent ? [] : deltas(plan, currentEntitlements);
              return (
                // Name and action on one line, then the allowances as a real
                // grid. They used to be an inline wrapped list, so four
                // numbers of different magnitudes ran together into one grey
                // sentence and nothing lined up between one plan and the next
                // -- which is the only comparison this card exists to support.
                <div
                  key={plan.key}
                  className={`rounded-xl border p-4 sm:p-5 ${
                    isCurrent ? "border-primary/40 bg-primary/5" : "border-border"
                  }`}
                >
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <p className="text-base font-bold">{plan.name}</p>
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

                  {/* Four columns on desktop, two on a phone, so the same
                      allowance sits in the same place on every card and the
                      eye can run down a column. */}
                  <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-4">
                    {COMPARED.map(({ key, label }) => {
                      const tight = key === tightest;
                      return (
                        <div key={key}>
                          <dt
                            className={`text-xs font-semibold ${
                              tight ? "text-primary-strong" : "text-muted-foreground"
                            }`}
                          >
                            {label}
                          </dt>
                          {/* Accent rather than bold. Every figure here is
                              already bold, so bolding one more said nothing,
                              and the footnote explaining it sat three cards
                              below the first thing it applied to. */}
                          <dd
                            className={`mt-0.5 text-lg font-extrabold tabular-nums ${
                              tight ? "text-primary-strong" : ""
                            }`}
                          >
                            {(plan.entitlements[key] ?? 0).toLocaleString()}
                          </dd>
                        </div>
                      );
                    })}
                  </dl>

                  {/* Chips, not a comma-separated sentence. Each one is a
                      single fact and they are read by scanning for the sign,
                      which a run-on line actively prevents. */}
                  {delta.length ? (
                    <div className="mt-4 border-t border-border/70 pt-3">
                      <p className="text-xs text-muted-foreground">Against your plan</p>
                      <ul className="mt-1.5 flex flex-wrap gap-1.5">
                        {delta.map((d) => (
                          <li
                            key={d}
                            className={`rounded-full px-2.5 py-1 text-xs font-semibold ${
                              d.startsWith("+")
                                ? "bg-primary/10 text-primary-strong"
                                : "bg-surface-muted text-muted-foreground"
                            }`}
                          >
                            {d}
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
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
  );
}
