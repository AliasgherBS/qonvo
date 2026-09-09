import { Activity } from "lucide-react";

import type { IntegrationUsage } from "@/lib/api/connections";
import { formatRelative } from "@/lib/format";

/**
 * One line proving the integration has actually been used (teardown N3).
 *
 * "Connected" only says the token works. It does not say the rep has booked
 * anything or written a row, and answering that used to mean opening Google.
 *
 * Both numbers come from records that already existed: `bookings` rows for the
 * calendar, and the `skill_executions` idempotency ledger for a successful
 * `append_to_sheet`. Nothing here is estimated -- an integration with no usage
 * says so rather than showing a zero dressed up as a metric.
 */
export function UsageLine({ usage }: { usage: IntegrationUsage | undefined }) {
  if (!usage) return null;

  const plural = usage.unit === "booking" ? "bookings" : `${usage.unit}s`;
  const never = usage.unit === "booking" ? "No bookings yet" : "No rows written yet";

  return (
    <p className="flex items-center gap-2 text-sm text-muted-foreground">
      <Activity className="h-3.5 w-3.5 shrink-0" />
      {usage.lastAt === null ? (
        <span>{never}</span>
      ) : (
        <span>
          Last {usage.unit} {formatRelative(usage.lastAt)}
          {usage.monthCount > 0 ? (
            <>
              {" · "}
              <span className="font-medium text-foreground">
                {usage.monthCount} {usage.monthCount === 1 ? usage.unit : plural}
              </span>{" "}
              this month
            </>
          ) : null}
        </span>
      )}
    </p>
  );
}
