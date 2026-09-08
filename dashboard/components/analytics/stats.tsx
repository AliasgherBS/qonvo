"use client";

import { ArrowDownRight, ArrowUpRight } from "lucide-react";
import type { ReactNode } from "react";

import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

/**
 * Analytics tiles with a hierarchy (teardown Y2).
 *
 * Eight boxes of identical weight, five of them reading zero, is a page that
 * answers "is this working" with a wall of equally loud numbers. Two figures
 * are what the owner is buying -- replies their rep sent, and customers it
 * captured -- so those two are large and carry a comparison, and everything
 * else is a small stat.
 *
 * The comparison is against the previous window of the same length, computed
 * by the API. Nothing here derives a period, so the tile and the chart cannot
 * disagree about what "last 30 days" means.
 */

interface Change {
  label: string;
  direction: "up" | "down";
}

/**
 * The change, or nothing.
 *
 * Two cases have no honest percentage. Both windows at zero is not a decline,
 * it is a product nobody has used yet; and growth from zero is not a
 * percentage at all, which is why "+Infinity%" shows up on dashboards.
 */
export function change(current: number, previous: number): Change | null {
  if (previous === 0 && current === 0) return null;
  if (previous === 0) return { label: "up from none", direction: "up" };
  if (current === previous) return null;
  const pct = Math.round(((current - previous) / previous) * 100);
  if (pct === 0) return null; // rounds to nothing: say nothing
  return { label: `${pct > 0 ? "+" : ""}${pct}%`, direction: pct > 0 ? "up" : "down" };
}

function Delta({ current, previous, rangeDays }: { current: number; previous: number; rangeDays: number }) {
  const delta = change(current, previous);
  if (!delta) {
    return (
      <p className="mt-2 text-xs text-muted-foreground">
        Nothing in the previous {rangeDays} days to compare with.
      </p>
    );
  }
  const Icon = delta.direction === "up" ? ArrowUpRight : ArrowDownRight;
  return (
    <p className="mt-2 flex items-center gap-1.5 text-xs font-semibold">
      <span
        className={cn(
          "inline-flex items-center gap-0.5",
          delta.direction === "up" ? "text-primary-strong" : "text-warning",
        )}
      >
        <Icon className="h-3.5 w-3.5" />
        {delta.label}
      </span>
      <span className="font-normal text-muted-foreground">
        vs the previous {rangeDays} days ({previous.toLocaleString()})
      </span>
    </p>
  );
}

export function HeroStat({
  label,
  value,
  previous,
  rangeDays,
  caption,
}: {
  label: string;
  value: number;
  previous: number;
  rangeDays: number;
  /** What the number is made of, or what it means. Not decoration: "24" with
      no unit is the reason nobody trusts a dashboard. */
  caption: ReactNode;
}) {
  return (
    <Card>
      <CardContent className="pt-5">
        <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{label}</p>
        <p className="mt-1 text-4xl font-extrabold tracking-tight tabular-nums">
          {value.toLocaleString()}
        </p>
        <Delta current={value} previous={previous} rangeDays={rangeDays} />
        <p className="mt-2 text-xs text-muted-foreground">{caption}</p>
      </CardContent>
    </Card>
  );
}

export function SmallStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-border bg-surface px-4 py-3">
      <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
        {label}
      </p>
      <p className="mt-0.5 text-lg font-bold tracking-tight tabular-nums">{value}</p>
    </div>
  );
}
