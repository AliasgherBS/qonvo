"use client";

import { AlertTriangle, Check, Gauge, PauseCircle } from "lucide-react";
import Link from "next/link";

import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { adminFleetUsage, type TenantUsage, type UsageMeter } from "@/lib/api";
import { useApi, useAuthToken } from "@/lib/use-api";

/**
 * Every tenant against its limits, worst first.
 *
 * This is the screen that catches a runaway tenant before the invoice does,
 * which only works if the ordering does the noticing rather than the operator.
 * The API sorts, so this renders in the order it receives.
 *
 * The numbers and the `state` on each meter come from the same
 * `services.usage.tenant_usage` an owner's own billing page reads. Nothing here
 * recomputes a ratio or a threshold: an operator and a customer looking at the
 * same tenant have to see the same thing, and the operator is the one least
 * able to notice if they do not.
 */

const TONE: Record<string, string> = {
  ok: "text-muted-foreground",
  near: "text-warning",
  over: "text-danger",
};

/** Only the meters worth an operator's attention, named the way they read. */
const WATCHED: { key: keyof TenantUsage; label: string; unit?: string }[] = [
  { key: "messages", label: "msgs" },
  { key: "voiceMinutes", label: "voice", unit: "m" },
  { key: "seats", label: "seats" },
  { key: "knowledgeSources", label: "srcs" },
  { key: "knowledgeChars", label: "chars" },
  { key: "knowledgeUploadMb", label: "disk", unit: "MB" },
];

function Cell({ meter, unit }: { meter: UsageMeter; unit?: string }) {
  return (
    <span className={`tabular-nums ${TONE[meter.state] ?? TONE.ok}`}>
      {meter.used.toLocaleString()}
      <span className="opacity-50">/{meter.allowed.toLocaleString()}</span>
      {unit ? <span className="opacity-50">{unit}</span> : null}
    </span>
  );
}

export function FleetLimits() {
  const token = useAuthToken();
  const { data, loading, error } = useApi(() => adminFleetUsage.list({ token }), [token]);

  if (loading) {
    return (
      <div className="space-y-3 p-5">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-10 w-full" />
        ))}
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="p-5">
        <EmptyState
          icon={<Gauge className="h-5 w-5" />}
          title="Couldn't load limits"
          description={error ?? "No data."}
        />
      </div>
    );
  }

  const attention = data.filter((t) => t.worstState !== "ok").length;

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2 border-b border-border px-5 py-3 text-sm">
        {attention > 0 ? (
          <>
            <AlertTriangle className="h-4 w-4 shrink-0 text-warning" />
            <span className="font-semibold">
              {attention} of {data.length} {attention === 1 ? "tenant needs" : "tenants need"} a
              look
            </span>
          </>
        ) : (
          <>
            <Check className="h-4 w-4 shrink-0 text-primary-strong" />
            <span className="font-semibold">All {data.length} tenants within their limits</span>
          </>
        )}
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-foreground">
              <th className="px-5 py-2 font-semibold">Tenant</th>
              <th className="px-3 py-2 font-semibold">Plan</th>
              {WATCHED.map((w) => (
                <th key={w.label} className="px-3 py-2 font-semibold">
                  {w.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.map((t) => (
              <tr key={t.tenantId} className="border-b border-border last:border-0">
                <td className="px-5 py-2.5">
                  <Link
                    href={`/admin/tenants/${t.tenantId}`}
                    className="font-semibold underline-offset-2 hover:underline"
                  >
                    {t.tenantName ?? t.tenantId.slice(0, 8)}
                  </Link>
                  {/* A paused rep explains a quiet tenant, which is otherwise
                      indistinguishable from a broken one. */}
                  {!t.repActive ? (
                    <span
                      className="ml-2 inline-flex items-center gap-1 text-xs text-warning"
                      title="The owner has paused their rep"
                    >
                      <PauseCircle className="h-3 w-3" />
                      paused
                    </span>
                  ) : null}
                </td>
                <td className="px-3 py-2.5 capitalize text-muted-foreground">
                  {t.plan}
                  {t.trialDaysLeft !== null ? (
                    <span className="ml-1 text-xs opacity-70">({t.trialDaysLeft}d)</span>
                  ) : null}
                </td>
                {WATCHED.map((w) => (
                  <td key={w.label} className="px-3 py-2.5">
                    <Cell meter={t[w.key] as UsageMeter} unit={w.unit} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
