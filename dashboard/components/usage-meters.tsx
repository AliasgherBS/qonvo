"use client";

import type { UsageMeter, TenantUsage } from "@/lib/api";

/**
 * One meter, and the set of them.
 *
 * Shared by the owner's billing page and the admin console, for the same
 * reason the computation behind them is shared: two renderings of the same
 * number drift, and the operator's copy would be the one that drifted.
 *
 * The colour comes from `state`, which the backend decides. A component that
 * compared the ratio to 0.8 itself would be a second place the threshold lives.
 */

const TONE: Record<string, { bar: string; text: string }> = {
  ok: { bar: "bg-primary", text: "text-muted-foreground" },
  near: { bar: "bg-warning", text: "text-warning" },
  over: { bar: "bg-danger", text: "text-danger" },
};

function format(n: number, unit?: string) {
  return unit ? `${n.toLocaleString()} ${unit}` : n.toLocaleString();
}

export function Meter({
  label,
  meter,
  unit,
  /** What actually happens at 100%. A full bar with no consequence named is
      just anxiety; the owner needs to know whether replies stop or voice does. */
  atLimit,
}: {
  label: string;
  meter: UsageMeter;
  unit?: string;
  atLimit?: string;
}) {
  const tone = TONE[meter.state] ?? TONE.ok;
  const pct = Math.round(meter.ratio * 100);

  return (
    <div>
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-sm font-semibold">{label}</span>
        <span className={`text-sm tabular-nums ${tone.text}`}>
          {format(meter.used, unit)} / {format(meter.allowed, unit)}
        </span>
      </div>
      <div
        className="mt-1.5 h-2 overflow-hidden rounded-full bg-border"
        role="progressbar"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={label}
      >
        <div className={`h-full rounded-full ${tone.bar}`} style={{ width: `${pct}%` }} />
      </div>
      {meter.state === "over" && atLimit ? (
        <p className="mt-1.5 text-xs font-semibold text-danger">{atLimit}</p>
      ) : null}
    </div>
  );
}

export function UsageMeters({ usage }: { usage: TenantUsage }) {
  const resets = new Date(usage.periodEnd).toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
  });

  return (
    <div className="space-y-5">
      <Meter
        label="Messages"
        meter={usage.messages}
        atLimit="Your rep has stopped replying until this resets or you upgrade."
      />
      <Meter
        label="Voice minutes"
        meter={usage.voiceMinutes}
        unit="min"
        atLimit="Voice replies are paused. Your rep is still answering by text."
      />
      <Meter label="Team seats" meter={usage.seats} />

      <div className="border-t border-border pt-5">
        <p className="mb-4 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Knowledge
        </p>
        <div className="space-y-5">
          <Meter label="Sources" meter={usage.knowledgeSources} />
          <Meter label="Total text" meter={usage.knowledgeChars} unit="chars" />
          <Meter label="Uploaded files" meter={usage.knowledgeUploadMb} unit="MB" />
        </div>
      </div>

      <p className="border-t border-border pt-4 text-xs text-muted-foreground">
        Messages and voice reset on {resets}. Knowledge limits are totals, not monthly.
      </p>
    </div>
  );
}
