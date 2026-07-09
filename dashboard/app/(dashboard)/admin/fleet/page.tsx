"use client";

import { Radio } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { adminFleet, type FleetSession, type SessionStatus } from "@/lib/api";
import { useApi } from "@/lib/use-api";

const STATUS_TONE: Record<SessionStatus, "success" | "warning" | "danger" | "default"> = {
  WORKING: "success",
  STARTING: "warning",
  SCAN_QR_CODE: "warning",
  STOPPED: "default",
  FAILED: "danger",
};

export default function AdminFleetPage() {
  const { data, loading, error, refetch } = useApi(() => adminFleet.sessions());

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-extrabold tracking-tight">Fleet health</h1>
        <p className="text-sm text-muted-foreground">
          Every WAHA session across every tenant — statuses, webhook failures, restarts.
        </p>
      </div>

      <div className="overflow-hidden rounded-2xl border border-border bg-surface">
        {loading ? (
          <div className="space-y-3 p-5">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </div>
        ) : error ? (
          <div className="p-5">
            <EmptyState
              icon={<Radio className="h-5 w-5" />}
              title="Can't reach the backend yet"
              description="Session health will populate once the fleet API is connected."
              action={
                <Button variant="outline" size="sm" onClick={refetch}>
                  Retry
                </Button>
              }
            />
          </div>
        ) : !data || data.length === 0 ? (
          <div className="p-5">
            <EmptyState
              icon={<Radio className="h-5 w-5" />}
              title="No sessions yet"
              description="Sessions appear here as tenants connect their WhatsApp numbers."
            />
          </div>
        ) : (
          <FleetTable sessions={data} onRestart={refetch} />
        )}
      </div>
    </div>
  );
}

function FleetTable({ sessions, onRestart }: { sessions: FleetSession[]; onRestart: () => void }) {
  return (
    <table className="w-full text-sm">
      <thead className="text-left text-xs font-bold uppercase tracking-wider text-muted-foreground">
        <tr>
          <th className="px-5 py-3">Session</th>
          <th className="px-5 py-3">Tenant</th>
          <th className="px-5 py-3">Status</th>
          <th className="px-5 py-3">Webhook failures</th>
          <th className="px-5 py-3" />
        </tr>
      </thead>
      <tbody className="divide-y divide-border">
        {sessions.map((session) => (
          <tr key={session.name}>
            <td className="px-5 py-3 font-semibold">{session.name}</td>
            <td className="px-5 py-3 text-muted-foreground">{session.tenantName}</td>
            <td className="px-5 py-3">
              <Badge tone={STATUS_TONE[session.status]}>{session.status}</Badge>
            </td>
            <td className="px-5 py-3 text-muted-foreground">{session.webhookFailureCount}</td>
            <td className="px-5 py-3 text-right">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => adminFleet.restart(session.name).then(onRestart).catch(() => undefined)}
              >
                Restart
              </Button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
