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
          Volume, speed, and outcomes over the last 30 days — proof your AI rep is pulling its weight.
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
            <p className="mt-3 text-sm text-muted-foreground">No knowledge gaps yet — nice.</p>
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
  return (
    <div className="mt-4 flex h-40 items-end gap-1 overflow-x-auto">
      {daily.map((d) => {
        const total = d.messagesIn + d.messagesOut;
        const height = Math.round((total / max) * 100);
        return (
          <div key={d.day} className="flex min-w-[8px] flex-1 flex-col items-center gap-1" title={`${d.day}: ${total} messages`}>
            <div className="flex w-full flex-1 items-end">
              <div
                className="w-full rounded-t bg-primary/70"
                style={{ height: `${Math.max(height, total > 0 ? 4 : 0)}%` }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
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
