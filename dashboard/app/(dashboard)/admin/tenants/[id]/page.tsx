"use client";

import { ArrowLeft, Building2 } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";

import { TenantConfigForm } from "@/components/tenant-config-form";
import { TenantLifecycleCard } from "@/components/tenant-lifecycle-card";
import { TenantSupportCard } from "@/components/tenant-support-card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { adminTenants, type TenantStatus } from "@/lib/api";
import { useApi, useAuthToken } from "@/lib/use-api";

const STATUS_TONE: Record<TenantStatus, "success" | "warning" | "default"> = {
  active: "success",
  onboarding: "warning",
  suspended: "default",
};

export default function AdminTenantDetailPage() {
  const params = useParams<{ id: string }>();
  const tenantId = params.id;
  const token = useAuthToken();

  const { data: tenant, loading: tenantLoading, error: tenantError, refetch: refetchTenant } = useApi(
    () => adminTenants.get(tenantId, { token }),
    [tenantId, token],
  );
  const { data: config, loading: configLoading, error: configError, refetch: refetchConfig } = useApi(
    () => adminTenants.getConfig(tenantId, { token }),
    [tenantId, token],
  );

  return (
    <div className="max-w-3xl space-y-6">
      <div>
        <Link href="/admin/tenants" className="inline-flex items-center gap-1.5 text-sm font-semibold text-muted-foreground hover:text-foreground">
          <ArrowLeft className="h-4 w-4" />
          All tenants
        </Link>
      </div>

      {tenantLoading ? (
        <Skeleton className="h-20 w-full rounded-2xl" />
      ) : tenantError || !tenant ? (
        <Card>
          <CardContent>
            <EmptyState
              icon={<Building2 className="h-5 w-5" />}
              title="Couldn't load tenant"
              description={tenantError ?? "This tenant couldn't be found."}
              action={
                <Button variant="outline" size="sm" onClick={refetchTenant}>
                  Retry
                </Button>
              }
            />
          </CardContent>
        </Card>
      ) : (
        <div className="flex items-center justify-between gap-4 rounded-2xl border border-border bg-surface p-5">
          <div>
            <h1 className="text-2xl font-extrabold tracking-tight">{tenant.name}</h1>
            <p className="text-sm text-muted-foreground">
              {tenant.ownerName} · {tenant.ownerEmail}
            </p>
          </div>
          <Badge tone={STATUS_TONE[tenant.status]}>{tenant.status}</Badge>
        </div>
      )}

      {tenant ? <TenantLifecycleCard tenant={tenant} onChanged={refetchTenant} /> : null}
      {tenant ? <TenantSupportCard tenant={tenant} /> : null}

      <div>
        <h2 className="mb-3 text-lg font-bold tracking-tight">Configuration</h2>
        {configLoading ? (
          <div className="space-y-3">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-24 w-full rounded-2xl" />
            ))}
          </div>
        ) : configError || !config ? (
          <Card>
            <CardContent>
              <EmptyState
                icon={<Building2 className="h-5 w-5" />}
                title="Couldn't load config"
                description={configError ?? "This tenant's config couldn't be loaded."}
                action={
                  <Button variant="outline" size="sm" onClick={refetchConfig}>
                    Retry
                  </Button>
                }
              />
            </CardContent>
          </Card>
        ) : (
          <TenantConfigForm
            config={config}
            onSave={(next) => adminTenants.updateConfig(tenantId, next, { token }).then(() => undefined)}
          />
        )}
      </div>
    </div>
  );
}
