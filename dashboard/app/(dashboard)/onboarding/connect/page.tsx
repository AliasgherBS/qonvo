"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ConnectCard } from "@/components/whatsapp/connect-card";
import { SessionStatusCard } from "@/components/whatsapp/session-status-card";
import { connections } from "@/lib/api/connections";
import { useApi, useAuthToken } from "@/lib/use-api";

/**
 * The WhatsApp page: a status page first, a setup form second (teardown W1).
 *
 * It used to be only the setup form, so a tenant with a linked number that had
 * received messages two days ago saw the same empty connect form as a brand new
 * one -- no number, no state, no last event, and no way to restart. That also
 * meant a dropped session could only be recovered from the internal admin
 * console, which made every disconnection a support ticket.
 */
export default function WhatsappPage() {
  const token = useAuthToken();
  const { data, loading, error, refetch } = useApi(() => connections.list({ token }), [token]);
  const [addingAnother, setAddingAnother] = useState(false);

  const linked = data ?? [];
  const hasSession = linked.length > 0;

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div>
        <h1 className="text-2xl font-extrabold tracking-tight">WhatsApp</h1>
        <p className="text-sm text-muted-foreground">
          {hasSession
            ? "Whether your rep is plugged in, and what to do when it is not."
            : "Link the business number Qonvo should watch."}
        </p>
      </div>

      {loading ? (
        <Card>
          <CardContent className="space-y-3 pt-5">
            <Skeleton className="h-6 w-48" />
            <Skeleton className="h-16 w-full" />
            <Skeleton className="h-10 w-40" />
          </CardContent>
        </Card>
      ) : error && !data ? (
        <Card>
          <CardContent className="pt-5 text-sm text-muted-foreground">
            {error}
            <Button variant="outline" size="sm" className="ml-3" onClick={refetch}>
              Retry
            </Button>
          </CardContent>
        </Card>
      ) : (
        <>
          {linked.map((session) => (
            <SessionStatusCard
              key={session.id}
              session={session}
              token={token}
              onChanged={refetch}
            />
          ))}

          {/* The connect form is what a tenant with no session sees, not the
              whole page. A second number is deliberately behind a click: most
              businesses have one, and an always-visible "connect" form on a
              working connection is what made the page read as unconfigured. */}
          {!hasSession || addingAnother ? (
            <ConnectCard
              askLabel={hasSession}
              token={token}
              onCreated={() => {
                setAddingAnother(false);
                refetch();
              }}
            />
          ) : (
            <Button variant="ghost" size="sm" onClick={() => setAddingAnother(true)}>
              Link another number
            </Button>
          )}
        </>
      )}
    </div>
  );
}
