"use client";

import { Meter } from "@/components/usage-meters";
import { Skeleton } from "@/components/ui/skeleton";
import type { KnowledgeUsage } from "@/lib/api/knowledge-extras";

/**
 * The three knowledge caps, on the page they govern (teardown K3).
 *
 * All three were metered against the plan and shown only on the billing page.
 * The moment an owner needs the number is while they are dropping the ninth PDF
 * on the zone above this, not while they are reading an invoice.
 *
 * Worst-first, because the only one that matters is the one about to fill. The
 * severity comes from `meter.state`, which the backend decides -- comparing the
 * ratio to 0.8 here would be a second place the threshold lives.
 */

const SEVERITY: Record<string, number> = { over: 0, near: 1, ok: 2 };

/** What actually happens at 100%, per meter. A full bar with no consequence
    named is just anxiety. */
const AT_LIMIT: Record<string, string> = {
  sources: "You cannot add another source until you delete one or move to a larger plan.",
  chars: "New entries and crawls are refused. Your rep still answers from what it has.",
  uploadMb: "New file uploads are refused. Delete a file you no longer need, or upgrade.",
};

export function KnowledgeCaps({
  usage,
  loading,
}: {
  usage: KnowledgeUsage | null;
  loading: boolean;
}) {
  if (loading && !usage) {
    return (
      <div className="rounded-2xl border border-border bg-surface p-5">
        <Skeleton className="h-3 w-24" />
        <div className="mt-4 space-y-4">
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-8 w-full" />
        </div>
      </div>
    );
  }
  // A missing usage read must not remove the sources table below it. The caps
  // are enforced on write regardless of whether this panel rendered.
  if (!usage) return null;

  const meters = [
    { key: "sources", label: "Sources", meter: usage.sources, unit: undefined },
    { key: "chars", label: "Text stored", meter: usage.chars, unit: "chars" },
    { key: "uploadMb", label: "Uploaded files", meter: usage.uploadMb, unit: "MB" },
  ].sort(
    (a, b) =>
      (SEVERITY[a.meter.state] ?? 2) - (SEVERITY[b.meter.state] ?? 2) ||
      b.meter.ratio - a.meter.ratio,
  );

  return (
    <div className="rounded-2xl border border-border bg-surface p-5">
      <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        What your plan allows
      </p>
      <div className="mt-4 grid gap-5 sm:grid-cols-3">
        {meters.map((m) => (
          <Meter
            key={m.key}
            label={m.label}
            meter={m.meter}
            unit={m.unit}
            atLimit={AT_LIMIT[m.key]}
          />
        ))}
      </div>
      <p className="mt-4 border-t border-border pt-4 text-xs text-muted-foreground">
        When one of these fills, that kind of knowledge stops being accepted. Nothing you have
        already added is lost and your rep keeps answering from it. These are totals, not monthly
        allowances.
      </p>
    </div>
  );
}
