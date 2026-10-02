"use client";

import { BarChart3 } from "lucide-react";
import { useState } from "react";

import { EmptyState } from "@/components/ui/empty-state";
import type { AnalyticsDailyPoint } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * Two stacked series by day, with a hover card (teardown Y1, and the analytics
 * views pass).
 *
 * It began as message counts only, inline on the analytics page. It is a
 * component taking accessors now because the voice view asks the identical
 * question of different numbers, and a second copy of a chart is a second copy
 * of the bug this one already had.
 *
 * **The bug worth remembering**, since the markup still looks like it could
 * come back: the row was `h-40 items-end`, and `align-items: flex-end` sizes
 * each column to its content rather than stretching it, so every column had no
 * definite height and every percentage resolved against zero. The chart
 * painted nothing while carrying correct data, on the one page whose job is to
 * say whether the product is working. `items-stretch` plus `h-full` is why it
 * draws.
 *
 * Days with no traffic are filled in before anything is drawn (finding F10).
 * The endpoint returns only days that have a usage row, so a gap arrived as
 * three evenly spaced bars labelled 5 Sep, 6 Sep, 8 Sep: a quiet day rendered
 * as continuity and the axis lied about time. Zero-height columns are the
 * honest shape and also the interesting one, because a run of empty days next
 * to a busy one is the thing an owner needs to see.
 *
 * The hover card replaces a `title` attribute. A native tooltip waits a second,
 * cannot be styled, never appears on a touch device and does not appear on
 * keyboard focus at all, which made the numbers behind the chart effectively
 * unreachable for anyone not using a mouse slowly.
 */

export type DayChartSeries = {
  /** Reads the lower (received) value from a day. */
  valueIn: (d: AnalyticsDailyPoint) => number;
  /** Reads the upper (sent) value from a day. */
  valueOut: (d: AnalyticsDailyPoint) => number;
  labelIn: string;
  labelOut: string;
  /** Renders one value for people: "12", "1m 30s". */
  format: (value: number) => string;
  /** Shown when this series has nothing in it. Per series, because "no voice
   *  yet" and "no messages yet" are different facts with different next steps. */
  emptyTitle: string;
  emptyBody: string;
};

export function DayChart({
  daily: sparse,
  series,
}: {
  daily: AnalyticsDailyPoint[];
  series: DayChartSeries;
}) {
  const [active, setActive] = useState<number | null>(null);
  const daily = withEmptyDays(sparse);

  const totals = daily.map((d) => series.valueIn(d) + series.valueOut(d));

  // Two ways to have nothing to draw, and they used to be one: no days at all,
  // or days that are all zero for THIS series. The second appeared the moment
  // there was a second view -- a tenant with plenty of messages and no voice
  // got a full axis, a full set of date labels and no bars, which is the
  // "chart paints nothing while the page insists it is fine" failure this
  // component already had once, wearing a different hat.
  if (daily.length === 0 || totals.every((t) => t === 0)) {
    return (
      <div className="mt-3">
        <EmptyState
          icon={<BarChart3 className="h-5 w-5" />}
          title={series.emptyTitle}
          description={series.emptyBody}
        />
      </div>
    );
  }

  const max = Math.max(1, ...totals);
  // Dropped when the top of the axis is 1: round(0.5) is 1, so the midpoint
  // and the top both read "1" and the scale claims two different heights are
  // the same number.
  const midLabel = max >= 2 ? series.format(Math.round(max / 2)) : "";

  // At most seven date labels, whatever the range. Thirty of them across the
  // card overlap into a grey smear, which is a different way of saying nothing.
  const stride = Math.max(1, Math.ceil(daily.length / 7));
  const showLabel = (i: number) => i === daily.length - 1 || i % stride === 0;

  const hovered = active === null ? null : daily[active];

  return (
    <div className="mt-4 flex gap-2">
      {/* The scale. Without it a tall bar means "the most there has been",
          which is not a quantity.

          pt-20 mirrors the plot area's, so the two baselines line up. Both
          need it rather than the flex parent, because the space is inside the
          scroll container by necessity -- see the hover card below. */}
      <div className="shrink-0 pt-20">
        <div className="flex h-40 w-14 flex-col justify-between pb-px text-right text-[10px] font-semibold tabular-nums text-muted-foreground">
          <span>{series.format(max)}</span>
          <span>{midLabel}</span>
          <span>{series.format(0)}</span>
        </div>
      </div>

      {/* pt-20 is what makes the hover card visible. `overflow-x-auto` makes
          this a scroll container, and a scroll container clips on BOTH axes --
          so a card positioned above the bars with a negative offset was drawn
          and then cut off, which is exactly what it looked like. The padding
          is inside the scrollable box, so a card sitting in it is not
          overflow at all. Reserved whether or not anything is hovered, so the
          card does not push the chart around when it appears. */}
      <div className="min-w-0 flex-1 overflow-x-auto pt-20">
        {/* relative, so the hover card can be positioned against the plot area
            rather than against the page. */}
        <div className="relative">
          {hovered ? (
            <div
              role="status"
              // Positioned over the column it describes and nudged inside the
              // plot at the edges, because a card centred on the first or last
              // bar would hang off the card it lives in.
              style={{
                left: `${((active! + 0.5) / daily.length) * 100}%`,
                transform: `translateX(${edgeShift(active!, daily.length)})`,
              }}
              className="pointer-events-none absolute -top-1 z-10 w-max -translate-y-full rounded-xl border border-border bg-surface px-3 py-2 text-xs shadow-lg"
            >
              <p className="font-bold tabular-nums">{longDay(hovered.day)}</p>
              <p className="mt-1 flex items-center gap-1.5 text-muted-foreground">
                <span className="h-2 w-2 shrink-0 rounded-sm bg-primary" />
                {series.labelOut}
                <span className="font-semibold tabular-nums text-foreground">
                  {series.format(series.valueOut(hovered))}
                </span>
              </p>
              <p className="mt-0.5 flex items-center gap-1.5 text-muted-foreground">
                <span className="h-2 w-2 shrink-0 rounded-sm bg-primary/40" />
                {series.labelIn}
                <span className="font-semibold tabular-nums text-foreground">
                  {series.format(series.valueIn(hovered))}
                </span>
              </p>
            </div>
          ) : null}

          {/* items-stretch, not items-end: the columns must take the row's
              height so their children have something to be a percentage of.

              justify-between, because the columns are capped at 56px: with a
              week of data and a wide card, flex-1 leaves all the slack on the
              right and the bars bunch against a full-width baseline. Spreading
              them puts the last bar at today's end of the axis. */}
          <div
            className="flex h-40 items-stretch justify-between gap-1 border-b border-border"
            onMouseLeave={() => setActive(null)}
          >
            {daily.map((d, i) => {
              const total = totals[i];
              // A day with traffic always shows a sliver. Rounding a real 0.4%
              // to nothing reads as a day the product was off.
              const pct = total > 0 ? Math.max((total / max) * 100, 2) : 0;
              const outShare = total > 0 ? (series.valueOut(d) / total) * 100 : 0;
              return (
                // A button, so the figures are reachable by keyboard. The whole
                // column is the target rather than the drawn bar: a zero day
                // has no bar to aim at, and "nothing happened here" is a fact
                // worth being able to check.
                <button
                  type="button"
                  key={d.day}
                  onMouseEnter={() => setActive(i)}
                  onFocus={() => setActive(i)}
                  onBlur={() => setActive(null)}
                  aria-label={`${longDay(d.day)}: ${series.format(series.valueOut(d))} ${series.labelOut}, ${series.format(series.valueIn(d))} ${series.labelIn}`}
                  className={cn(
                    "flex h-full min-w-[6px] max-w-[56px] flex-1 flex-col justify-end rounded-t transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                    active === i && "bg-surface-muted",
                  )}
                >
                  <div
                    className="flex w-full flex-col-reverse overflow-hidden rounded-t"
                    style={{ height: `${pct}%` }}
                  >
                    <div
                      className="w-full bg-primary/40"
                      style={{ height: `${100 - outShare}%` }}
                    />
                    <div className="w-full bg-primary" style={{ height: `${outShare}%` }} />
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        <div className="flex justify-between gap-1 pt-1.5">
          {daily.map((d, i) => (
            <div
              key={d.day}
              className={cn(
                "min-w-[6px] max-w-[56px] flex-1 text-center text-[10px] tabular-nums",
                active === i ? "font-bold text-foreground" : "text-muted-foreground",
              )}
            >
              {showLabel(i) || active === i ? shortDay(d.day) : " "}
            </div>
          ))}
        </div>

        <div className="flex items-center gap-4 pt-2 text-[11px] text-muted-foreground">
          <span className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-sm bg-primary" />
            {series.labelOut}
          </span>
          <span className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-sm bg-primary/40" />
            {series.labelIn}
          </span>
        </div>
      </div>
    </div>
  );
}

/**
 * How far to pull the hover card back from the plot edge.
 *
 * Centred on the column everywhere except the first and last few, where a
 * centred card would hang outside the card it lives in and be clipped.
 */
function edgeShift(index: number, count: number): string {
  const position = (index + 0.5) / count;
  if (position < 0.15) return "0%";
  if (position > 0.85) return "-100%";
  return "-50%";
}

/**
 * One entry per calendar day between the first and last day present.
 *
 * Bounded by the data rather than by the selected range on purpose: the
 * response says how many days were asked for but not which day the window ends
 * on, and inventing that boundary from the browser's clock would put a day that
 * has not happened yet in UTC on the end of the axis. That is a different way
 * to be wrong about time, and this fix is about not being wrong about time.
 *
 * Guarded on both ends: an unparseable day, or a span wider than any real
 * range, returns the input untouched. A chart that paints something imperfect
 * beats one that stops painting, which is the failure this chart already had
 * once.
 */
const MAX_FILLED_DAYS = 400;

function withEmptyDays(daily: AnalyticsDailyPoint[]): AnalyticsDailyPoint[] {
  if (daily.length < 2) return daily;

  const ordered = [...daily].sort((a, b) => a.day.localeCompare(b.day));
  const first = Date.parse(`${ordered[0].day}T00:00:00Z`);
  const last = Date.parse(`${ordered[ordered.length - 1].day}T00:00:00Z`);
  if (Number.isNaN(first) || Number.isNaN(last)) return daily;

  const span = Math.round((last - first) / 86_400_000) + 1;
  if (span <= ordered.length || span > MAX_FILLED_DAYS) return ordered;

  const known = new Map(ordered.map((d) => [d.day, d]));
  const filled: AnalyticsDailyPoint[] = [];
  for (let i = 0; i < span; i += 1) {
    const day = new Date(first + i * 86_400_000).toISOString().slice(0, 10);
    filled.push(
      known.get(day) ?? {
        day,
        messagesIn: 0,
        messagesOut: 0,
        voiceSecondsIn: 0,
        voiceSecondsOut: 0,
      },
    );
  }
  return filled;
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

/** "2026-09-05" as "Fri, 5 Sep". The hover card has room for the weekday. */
function longDay(day: string): string {
  const parsed = new Date(`${day}T00:00:00Z`);
  if (Number.isNaN(parsed.getTime())) return day;
  return parsed.toLocaleDateString(undefined, {
    weekday: "short",
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  });
}
