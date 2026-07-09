"use client";

import { BarChart3 } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { analytics } from "@/lib/api";
import { useApi } from "@/lib/use-api";

const TILES: { key: keyof ReturnType<typeof buildTiles>; label: string }[] = [
  { key: "messagesIn", label: "Messages in" },
  { key: "messagesOut", label: "Messages out" },
  { key: "avgResponseTimeSeconds", label: "Avg. response time" },
  { key: "resolutionRate", label: "Resolution rate" },
  { key: "handoffRate", label: "Handoff rate" },
  { key: "leadsCount", label: "Leads captured" },
  { key: "bookingsCount", label: "Bookings made" },
];

function buildTiles(summary: {
  messagesIn: number;
  messagesOut: number;
  avgResponseTimeSeconds: number;
  resolutionRate: number;
  handoffRate: number;
  leadsCount: number;
  bookingsCount: number;
}) {
  return {
    messagesIn: `${summary.messagesIn}`,
    messagesOut: `${summary.messagesOut}`,
    avgResponseTimeSeconds: `${summary.avgResponseTimeSeconds}s`,
    resolutionRate: `${Math.round(summary.resolutionRate * 100)}%`,
    handoffRate: `${Math.round(summary.handoffRate * 100)}%`,
    leadsCount: `${summary.leadsCount}`,
    bookingsCount: `${summary.bookingsCount}`,
  };
}

export default function AnalyticsPage() {
  const { data, loading, error, refetch } = useApi(() => analytics.summary());
  const tiles = data ? buildTiles(data) : null;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-extrabold tracking-tight">Analytics</h1>
        <p className="text-sm text-muted-foreground">
          Volume, speed, and outcomes — proof your AI rep is pulling its weight.
        </p>
      </div>

      {loading ? (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
          {Array.from({ length: 7 }).map((_, i) => (
            <Card key={i}>
              <CardContent className="space-y-2 pt-5">
                <Skeleton className="h-3 w-2/3" />
                <Skeleton className="h-7 w-1/2" />
              </CardContent>
            </Card>
          ))}
        </div>
      ) : error || !tiles ? (
        <EmptyState
          icon={<BarChart3 className="h-5 w-5" />}
          title="No analytics yet"
          description="Stats fill in once conversations start flowing through your number."
        />
      ) : (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
          {TILES.map(({ key, label }) => (
            <Card key={key}>
              <CardContent className="space-y-1 pt-5">
                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{label}</p>
                <p className="text-2xl font-extrabold tracking-tight">{tiles[key]}</p>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      <Card>
        <CardContent className="pt-5">
          <p className="mb-3 text-sm font-bold">Top unanswered questions</p>
          {data?.topUnansweredQuestions?.length ? (
            <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
              {data.topUnansweredQuestions.map((question) => (
                <li key={question}>{question}</li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted-foreground">
              Nothing to show yet — knowledge gaps surface here once customers start asking.
            </p>
          )}
        </CardContent>
      </Card>

      {error ? (
        <button onClick={refetch} className="text-sm font-semibold text-primary-strong underline">
          Retry
        </button>
      ) : null}
    </div>
  );
}
