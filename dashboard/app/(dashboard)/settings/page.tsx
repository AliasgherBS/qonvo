"use client";

import { TenantConfigForm } from "@/components/tenant-config-form";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { config } from "@/lib/api";
import { useApi, useAuthToken } from "@/lib/use-api";

export default function SettingsPage() {
  const token = useAuthToken();
  const { data, loading, error, refetch } = useApi(() => config.get({ token }), [token]);

  return (
    <div className="max-w-3xl space-y-6">
      <div>
        <h1 className="text-2xl font-extrabold tracking-tight">Settings</h1>
        <p className="text-sm text-muted-foreground">
          Persona, languages, hours, and escalation — how your AI rep shows up for customers.
        </p>
      </div>

      {loading ? (
        <SettingsSkeleton />
      ) : error && !data ? (
        <Card>
          <CardContent className="text-sm text-muted-foreground">
            Can&apos;t reach the backend yet — settings will load once the API is connected.
            <Button variant="outline" size="sm" className="ml-3" onClick={refetch}>
              Retry
            </Button>
          </CardContent>
        </Card>
      ) : data ? (
        <TenantConfigForm config={data} onSave={(next) => config.update(next, { token }).then(() => undefined)} />
      ) : null}
    </div>
  );
}

function SettingsSkeleton() {
  return (
    <div className="space-y-6">
      {[0, 1, 2].map((i) => (
        <Card key={i}>
          <CardContent className="space-y-3 pt-5">
            <Skeleton className="h-4 w-1/4" />
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-2/3" />
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
