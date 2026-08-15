"use client";

import { Radio } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import {
  adminFleet,
  describeError,
  type FleetAction,
  type FleetSession,
  type SessionStatus,
} from "@/lib/api";
import { useApi, useAuthToken } from "@/lib/use-api";

const STATUS_TONE: Record<SessionStatus, "success" | "warning" | "danger" | "default"> = {
  WORKING: "success",
  STARTING: "warning",
  SCAN_QR_CODE: "warning",
  STOPPED: "default",
  FAILED: "danger",
};

const ACTIONS: { action: FleetAction; label: string; destructive?: boolean }[] = [
  { action: "restart", label: "Restart" },
  { action: "start", label: "Start" },
  { action: "stop", label: "Stop" },
  { action: "logout", label: "Logout", destructive: true },
];

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
              title="Couldn't load"
              description={error}
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
          <FleetTable sessions={data} onChanged={refetch} />
        )}
      </div>
    </div>
  );
}

function FleetTable({ sessions, onChanged }: { sessions: FleetSession[]; onChanged: () => void }) {
  return (
    <table className="w-full text-sm">
      <thead className="text-left text-xs font-bold uppercase tracking-wider text-muted-foreground">
        <tr>
          <th className="px-5 py-3">Session</th>
          <th className="px-5 py-3">Tenant</th>
          <th className="px-5 py-3">Status</th>
          <th className="px-5 py-3 text-right">Control</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-border">
        {sessions.map((session) => (
          <FleetRow key={session.name} session={session} onChanged={onChanged} />
        ))}
      </tbody>
    </table>
  );
}

function FleetRow({ session, onChanged }: { session: FleetSession; onChanged: () => void }) {
  const token = useAuthToken();
  const { toast } = useToast();
  const [busy, setBusy] = useState<FleetAction | null>(null);
  const [confirm, setConfirm] = useState(false);

  async function run(action: FleetAction) {
    setBusy(action);
    try {
      const res = await adminFleet.action(session.name, action, { token });
      toast({
        title: `${action[0].toUpperCase()}${action.slice(1)} sent`,
        description: res.live_status ? `Live status: ${res.live_status}` : undefined,
        variant: "success",
      });
      onChanged();
    } catch (err) {
      toast({ title: "Action failed", description: describeError(err), variant: "error" });
    } finally {
      setBusy(null);
      setConfirm(false);
    }
  }

  return (
    <tr>
      <td className="px-5 py-3 font-semibold">{session.label || session.name}</td>
      <td className="px-5 py-3 text-muted-foreground">{session.tenantName}</td>
      <td className="px-5 py-3">
        <Badge tone={STATUS_TONE[session.status]}>{session.status}</Badge>
        {session.liveStatus && session.liveStatus !== session.status ? (
          <span className="ml-2 text-xs text-muted-foreground">live: {session.liveStatus}</span>
        ) : null}
      </td>
      <td className="px-5 py-3">
        <div className="flex flex-wrap justify-end gap-1.5">
          {ACTIONS.map(({ action, label, destructive }) => (
            <Button
              key={action}
              variant="outline"
              size="sm"
              disabled={busy !== null}
              className={destructive ? "border-danger/50 text-danger" : undefined}
              onClick={() => (destructive ? setConfirm(true) : run(action))}
            >
              {busy === action ? "…" : label}
            </Button>
          ))}
        </div>
      </td>

      <Dialog
        open={confirm}
        onClose={() => setConfirm(false)}
        title="Log out this session?"
        description={`Logging out unlinks the phone from "${session.tenantName ?? session.name}". Reconnecting needs a fresh QR scan by the owner.`}
      >
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={() => setConfirm(false)}>
            Cancel
          </Button>
          <Button
            className="border-danger/50 bg-danger text-danger-foreground hover:bg-danger/90"
            disabled={busy !== null}
            onClick={() => run("logout")}
          >
            {busy === "logout" ? "Logging out…" : "Log out"}
          </Button>
        </div>
      </Dialog>
    </tr>
  );
}
