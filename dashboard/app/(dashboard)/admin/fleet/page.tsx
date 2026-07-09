"use client";

import { ExternalLink, Radio } from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { adminFleet, type FleetSession, type SessionStatus } from "@/lib/api";
import { useApi, useAuthToken } from "@/lib/use-api";

const STATUS_TONE: Record<SessionStatus, "success" | "warning" | "danger" | "default"> = {
  WORKING: "success",
  STARTING: "warning",
  SCAN_QR_CODE: "warning",
  STOPPED: "default",
  FAILED: "danger",
};

export default function AdminFleetPage() {
  const token = useAuthToken();
  const { data, loading, error, refetch } = useApi(() => adminFleet.list({ token }), [token]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-extrabold tracking-tight">Fleet health</h1>
        <p className="text-sm text-muted-foreground">
          Every WAHA session across every tenant — live status, at a glance.
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
          <FleetTable sessions={data} />
        )}
      </div>
    </div>
  );
}

function FleetTable({ sessions }: { sessions: FleetSession[] }) {
  return (
    <table className="w-full text-sm">
      <thead className="text-left text-xs font-bold uppercase tracking-wider text-muted-foreground">
        <tr>
          <th className="px-5 py-3">Session</th>
          <th className="px-5 py-3">Tenant</th>
          <th className="px-5 py-3">Status</th>
          <th className="px-5 py-3" />
        </tr>
      </thead>
      <tbody className="divide-y divide-border">
        {sessions.map((session) => (
          <tr key={session.name}>
            <td className="px-5 py-3 font-semibold">{session.label || session.name}</td>
            <td className="px-5 py-3 text-muted-foreground">{session.tenantName}</td>
            <td className="px-5 py-3">
              <Badge tone={STATUS_TONE[session.status]}>{session.status}</Badge>
            </td>
            <td className="px-5 py-3 text-right">
              <Link
                href="/onboarding/connect"
                className="inline-flex h-8 items-center gap-1.5 rounded-full px-3.5 text-sm font-semibold text-foreground transition-colors hover:bg-surface-muted"
              >
                Connect
                <ExternalLink className="h-3.5 w-3.5" />
              </Link>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
