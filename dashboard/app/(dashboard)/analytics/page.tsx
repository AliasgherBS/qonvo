"use client";

import Link from "next/link";
import { useState } from "react";

import { DayChart } from "@/components/analytics/day-chart";
import { HeroStat, SmallStat } from "@/components/analytics/stats";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { analytics, type AnalyticsDailyPoint, type AnalyticsSummary } from "@/lib/api";
import { useApi, useAuthToken } from "@/lib/use-api";
import { cn } from "@/lib/utils";

/** The endpoint already took `?days=`; nothing on the page could change it. */
const RANGES = [
  { days: 7, label: "7 days" },
  { days: 30, label: "30 days" },
  { days: 90, label: "90 days" },
] as const;

export default function AnalyticsPage() {
  const token = useAuthToken();
  const [days, setDays] = useState<number>(30);
  const { data, loading, error, refetch } = useApi(
    () => analytics.summary({ days }, { token }),
    [token, days],
  );

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-extrabold tracking-tight">Analytics</h1>
          <p className="text-sm text-muted-foreground">
            What your rep did over the last {days} days, against the {days} before it.
          </p>
        </div>
        <div className="flex gap-2" role="group" aria-label="Date range">
          {RANGES.map((r) => (
            <button
              key={r.days}
              type="button"
              onClick={() => setDays(r.days)}
              aria-pressed={days === r.days}
              className={cn(
                "rounded-full px-4 py-1.5 text-sm font-semibold transition-colors",
                days === r.days
                  ? "bg-primary text-primary-foreground"
                  : "bg-surface-muted hover:bg-border",
              )}
            >
              {r.label}
            </button>
          ))}
        </div>
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

/**
 * The two questions the page answers, as a switch rather than as two charts.
 *
 * An owner asked "how long is a typical voice note" and nothing here could
 * answer it, while the same figures for text sat one card away. Voice and text
 * ask the same shape of question -- how many in, how many out, how long is one
 * -- of numbers that cannot share an axis: a chart mixing message counts and
 * seconds would have a y-axis measuring nothing.
 *
 * So the view swaps the numbers and the series, and the chart is the same
 * component reading different accessors.
 */
const VIEWS = [
  { key: "messages", label: "Messages" },
  { key: "voice", label: "Voice" },
] as const;

type ViewKey = (typeof VIEWS)[number]["key"];

function AnalyticsContent({ data }: { data: AnalyticsSummary }) {
  const [view, setView] = useState<ViewKey>("messages");
  const t = data.totals;
  const days = data.rangeDays;
  const leads = t.leads ?? 0;
  const bookings = t.bookings ?? 0;
  const orders = t.orders ?? 0;

  // Demoted, not deleted. Each of these is worth a glance and none of them is
  // the reason somebody pays for the product.
  //
  // "AI cost" is deliberately absent (teardown Y3). It was our cost of goods,
  // printed to the cent in front of somebody paying a monthly fee, and the
  // only question it invites is a margin conversation. The figure is still
  // recorded, still billed against, and still shown where it is operationally
  // useful: /admin/usage, which has a Cost column per tenant per month. The
  // endpoint no longer sends it either, so there is nothing here to hide.
  const smallStats: { label: string; value: string }[] = [
    { label: "Messages received", value: (t.messages_in ?? 0).toLocaleString() },
    { label: "Conversations", value: (t.conversations ?? 0).toLocaleString() },
    { label: "Needs human now", value: (t.needs_human ?? 0).toLocaleString() },
    { label: "Open handoffs", value: (t.handoffs_open ?? 0).toLocaleString() },
  ];

  const detail =
    view === "voice"
      ? {
          series: {
            valueIn: (d: AnalyticsDailyPoint) => d.voiceSecondsIn,
            valueOut: (d: AnalyticsDailyPoint) => d.voiceSecondsOut,
            labelIn: "Listened to",
            labelOut: "Spoken back",
            format: formatSeconds,
            emptyTitle: "No voice yet",
            emptyBody:
              "Your rep answers voice notes with voice notes. This charts once a customer sends one.",
          },
          figures: [
            {
              label: "Voice notes received",
              value: data.voice.inbound.count.toLocaleString(),
            },
            {
              label: "Voice replies sent",
              value: data.voice.outbound.count.toLocaleString(),
            },
            {
              label: "Average note received",
              value: formatSeconds(data.voice.inbound.avgSeconds),
            },
            {
              label: "Average reply spoken",
              value: formatSeconds(data.voice.outbound.avgSeconds),
            },
          ],
        }
      : {
          series: {
            valueIn: (d: AnalyticsDailyPoint) => d.messagesIn,
            valueOut: (d: AnalyticsDailyPoint) => d.messagesOut,
            labelIn: "Received",
            labelOut: "Replies sent",
            format: (n: number) => n.toLocaleString(),
            emptyTitle: "No activity yet",
            emptyBody: "Message volume will chart here as conversations come in.",
          },
          figures: [
            { label: "Received", value: (t.messages_in ?? 0).toLocaleString() },
            { label: "Replies sent", value: (t.messages_out ?? 0).toLocaleString() },
            {
              label: "Average question",
              value: formatChars(data.shape.inboundTextAvgChars),
            },
            {
              label: "Average reply",
              value: formatChars(data.shape.outboundTextAvgChars),
            },
          ],
        };

  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2">
        <HeroStat
          label="Messages answered"
          value={t.messages_out ?? 0}
          previous={t.prev_messages_out ?? 0}
          rangeDays={days}
          caption="Replies sent from your number, by the rep and by your team."
        />
        <HeroStat
          label="Bookings and leads"
          value={t.outcomes ?? 0}
          previous={t.prev_outcomes ?? 0}
          rangeDays={days}
          caption={
            // The breakdown, because a business uses one or two of these three
            // and the combined figure would otherwise hide which.
            `${bookings.toLocaleString()} bookings · ${leads.toLocaleString()} leads · ${orders.toLocaleString()} orders`
          }
        />
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {smallStats.map((s) => (
          <SmallStat key={s.label} label={s.label} value={s.value} />
        ))}
      </div>

      <Card>
        <CardContent className="pt-5">
          {/* The switcher sits on the card it governs rather than on the page,
              so it is unambiguous which numbers it changes. Everything above
              is true in both views. */}
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm font-bold">Day by day</p>
            <div className="flex gap-1" role="group" aria-label="Activity view">
              {VIEWS.map((v) => (
                <button
                  key={v.key}
                  type="button"
                  onClick={() => setView(v.key)}
                  aria-pressed={view === v.key}
                  className={cn(
                    "rounded-full px-3.5 py-1.5 text-xs font-bold transition-colors",
                    view === v.key
                      ? "bg-primary text-primary-foreground"
                      : "bg-surface-muted hover:bg-border",
                  )}
                >
                  {v.label}
                </button>
              ))}
            </div>
          </div>

          <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
            {detail.figures.map((f) => (
              <div key={f.label}>
                <p className="text-xs font-semibold text-muted-foreground">{f.label}</p>
                <p className="mt-0.5 text-xl font-extrabold tabular-nums">{f.value}</p>
              </div>
            ))}
          </div>

          <DayChart daily={data.daily} series={detail.series} />
        </CardContent>
      </Card>

      <Card>
        <CardContent className="pt-5">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <p className="text-sm font-bold">Top questions the bot couldn&apos;t answer</p>
            {/* This card reported a problem and offered nothing to do about it.
                Answering happens on Knowledge, so it says so. */}
            <Link href="/knowledge" className="text-xs font-semibold text-primary-strong hover:underline">
              Answer these in Knowledge
            </Link>
          </div>
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
 * Seconds as people say them. "45s", "2m 30s", "3m".
 *
 * Not decimal minutes: a voice note is a few seconds long, and "0.75 min" is a
 * worse answer to "how long is a typical voice note" than the question
 * deserves. The trailing seconds are dropped at a whole minute because "3m 0s"
 * reads as a measurement and "3m" reads as a duration.
 */
function formatSeconds(seconds: number): string {
  const whole = Math.max(0, Math.round(seconds));
  if (whole < 60) return `${whole}s`;
  const minutes = Math.floor(whole / 60);
  const rest = whole % 60;
  return rest === 0 ? `${minutes}m` : `${minutes}m ${rest}s`;
}

/** Characters, with the unit, because a bare number here means nothing. */
function formatChars(chars: number): string {
  return `${Math.round(chars).toLocaleString()} chars`;
}

function AnalyticsSkeleton() {
  return (
    <div className="space-y-6">
      {/* Shaped like what arrives: two large tiles then a row of small ones.
          A skeleton that lays out differently is a visible jump on every load. */}
      <div className="grid gap-4 sm:grid-cols-2">
        {[0, 1].map((i) => (
          <Card key={i}>
            <CardContent className="space-y-2 pt-5">
              <Skeleton className="h-3 w-1/3" />
              <Skeleton className="h-10 w-1/2" />
              <Skeleton className="h-3 w-2/3" />
            </CardContent>
          </Card>
        ))}
      </div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="space-y-2 rounded-xl border border-border bg-surface px-4 py-3">
            <Skeleton className="h-3 w-2/3" />
            <Skeleton className="h-5 w-1/2" />
          </div>
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
