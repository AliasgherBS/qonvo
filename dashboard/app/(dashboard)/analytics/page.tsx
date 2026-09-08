"use client";

import { BarChart3 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { analytics, type AnalyticsSummary } from "@/lib/api";
import { useApi, useAuthToken } from "@/lib/use-api";

const CURRENCY = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 });

export default function AnalyticsPage() {
  const token = useAuthToken();
  const { data, loading, error, refetch } = useApi(() => analytics.summary({ days: 30 }, { token }), [token]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-extrabold tracking-tight">Analytics</h1>
        <p className="text-sm text-muted-foreground">
          Volume, speed and outcomes over the last 30 days.
        </p>
      </div>

      {loading ? (
        <AnalyticsSkeleton />
      ) : error && !data ? (
        <Card>
          <CardContent className="text-sm text-muted-foreground">
            {error}
            <Button variant="outline" size="sm" className="ml-3" onClick={refetch}>
              Retry
            </Button>
          </CardContent>
        </Card>
      ) : data ? (
        <AnalyticsContent data={data} />
      ) : null}
    </div>
  );
}

function AnalyticsContent({ data }: { data: AnalyticsSummary }) {
  const t = data.totals;
  const stats: { label: string; value: string }[] = [
    { label: "Messages", value: String(t.messages ?? 0) },
    { label: "Conversations", value: String(t.conversations ?? 0) },
    { label: "Leads", value: String(t.leads ?? 0) },
    { label: "Bookings", value: String(t.bookings ?? 0) },
    { label: "Orders", value: String(t.orders ?? 0) },
    { label: "Needs human", value: String(t.needs_human ?? 0) },
    { label: "Open handoffs", value: String(t.handoffs_open ?? 0) },
    { label: "AI cost", value: CURRENCY.format(t.cost ?? 0) },
  ];

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        {stats.map((s) => (
          <Card key={s.label}>
            <CardContent className="pt-5">
              <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{s.label}</p>
              <p className="mt-1 text-2xl font-extrabold tracking-tight">{s.value}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      <Card>
        <CardContent className="pt-5">
          <p className="text-sm font-bold">Daily message volume</p>
          <VolumeChart daily={data.daily} />
        </CardContent>
      </Card>

      <Card>
        <CardContent className="pt-5">
          <p className="text-sm font-bold">Top questions the bot couldn&apos;t answer</p>
          {data.topGaps.length === 0 ? (
            <p className="mt-3 text-sm text-muted-foreground">No knowledge gaps yet.</p>
          ) : (
            <ul className="mt-3 space-y-2">
              {data.topGaps.map((g) => (
                <li key={g.question} className="flex items-center justify-between gap-3 text-sm">
                  <span className="truncate">{g.question}</span>
                  <span className="shrink-0 rounded-full bg-surface-muted px-2 py-0.5 text-xs font-semibold">
                    ×{g.count}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

/**
 * Message volume by day (teardown Y1).
 *
 * This drew nothing. The data was there and the markup was almost right: every
 * column carried a real percentage height and a working tooltip, and every one
 * measured zero pixels. The row was `h-40 items-end`, and `align-items:
 * flex-end` sizes each column to its content rather than stretching it to the
 * row, so the columns had no definite height and the percentages resolved
 * against zero. The empty state never fired either, because the data was not
 * empty -- the chart simply painted nothing, on the one page whose entire job
 * is to say whether the product is working.
 *
 * `items-stretch` plus `h-full` on the columns is the fix. The axis and the
 * dates are here because the teardown's second point stands: two bars across
 * eleven hundred pixels with no scale says very little even once it paints.
 *
 * Stacked in and out rather than one total, since both numbers are already in
 * the response and "we answered" is the interesting half.
 */
function VolumeChart({ daily }: { daily: AnalyticsSummary["daily"] }) {
  if (daily.length === 0) {
    return (
      <div className="mt-3">
        <EmptyState
          icon={<BarChart3 className="h-5 w-5" />}
          title="No activity yet"
          description="Message volume will chart here as conversations come in."
        />
      </div>
    );
  }

  const max = Math.max(1, ...daily.map((d) => d.messagesIn + d.messagesOut));

  // At most seven date labels, whatever the range. Thirty of them across the
  // card overlap into a grey smear, which is a different way of saying
  // nothing.
  const stride = Math.max(1, Math.ceil(daily.length / 7));
  const showLabel = (i: number) => i === daily.length - 1 || i % stride === 0;

  return (
    <div className="mt-4 flex gap-2">
      {/* The scale. Without it a tall bar means "the most there has been",
          which is not a quantity. */}
      <div className="flex h-40 w-9 shrink-0 flex-col justify-between pb-px text-right text-[10px] font-semibold tabular-nums text-muted-foreground">
        <span>{max}</span>
        <span>{Math.round(max / 2)}</span>
        <span>0</span>
      </div>

      <div className="min-w-0 flex-1 overflow-x-auto">
        {/* items-stretch, not items-end: the columns must take the row's
            height so their children have something to be a percentage of. */}
        {/* justify-between, because the columns are capped at 56px: with a
            week of data and a wide card, flex-1 leaves all the slack on the
            right and the bars bunch against a full-width baseline. Spreading
            them puts the last bar at today's end of the axis, where it
            belongs. */}
        <div className="flex h-40 items-stretch justify-between gap-1 border-b border-border">
          {daily.map((d) => {
            const total = d.messagesIn + d.messagesOut;
            // A day with traffic always shows a sliver. Rounding a real 0.4%
            // to nothing reads as a day the product was off.
            const pct = total > 0 ? Math.max((total / max) * 100, 2) : 0;
            const outShare = total > 0 ? (d.messagesOut / total) * 100 : 0;
            return (
              <div
                key={d.day}
                className="flex h-full min-w-[6px] max-w-[56px] flex-1 flex-col justify-end"
                title={`${d.day}: ${total} messages (${d.messagesIn} in, ${d.messagesOut} out)`}
              >
                <div
                  className="flex w-full flex-col-reverse overflow-hidden rounded-t"
                  style={{ height: `${pct}%` }}
                >
                  <div className="w-full bg-primary/40" style={{ height: `${100 - outShare}%` }} />
                  <div className="w-full bg-primary" style={{ height: `${outShare}%` }} />
                </div>
              </div>
            );
          })}
        </div>

        <div className="flex justify-between gap-1 pt-1.5">
          {daily.map((d, i) => (
            <div
              key={d.day}
              className="min-w-[6px] max-w-[56px] flex-1 text-center text-[10px] tabular-nums text-muted-foreground"
            >
              {showLabel(i) ? shortDay(d.day) : "\u00A0"}
            </div>
          ))}
        </div>

        <div className="flex items-center gap-4 pt-2 text-[11px] text-muted-foreground">
          <span className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-sm bg-primary" />
            Replies sent
          </span>
          <span className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-sm bg-primary/40" />
            Messages received
          </span>
        </div>
      </div>
    </div>
  );
}

/** "2026-09-05" as "5 Sep". Falls back to the raw string if it will not parse. */
function shortDay(day: string): string {
  const parsed = new Date(`${day}T00:00:00Z`);
  if (Number.isNaN(parsed.getTime())) return day;
  return parsed.toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  });
}

function AnalyticsSkeleton() {
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        {[0, 1, 2, 3, 4, 5, 6, 7].map((i) => (
          <Card key={i}>
            <CardContent className="space-y-2 pt-5">
              <Skeleton className="h-3 w-1/2" />
              <Skeleton className="h-7 w-2/3" />
            </CardContent>
          </Card>
        ))}
      </div>
      <Card>
        <CardContent className="pt-5">
          <Skeleton className="h-40 w-full" />
        </CardContent>
      </Card>
    </div>
  );
}
