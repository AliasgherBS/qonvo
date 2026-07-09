"use client";

import { Building2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { adminTenants, type AdminTenant, type TenantStatus } from "@/lib/api";
import { useApi } from "@/lib/use-api";

const STATUS_TONE: Record<TenantStatus, "success" | "warning" | "default"> = {
  active: "success",
  onboarding: "warning",
  suspended: "default",
};

export default function AdminTenantsPage() {
  const { data, loading, error, refetch } = useApi(() => adminTenants.list());

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-extrabold tracking-tight">Tenants</h1>
          <p className="text-sm text-muted-foreground">
            Every business on Qonvo — create tenants, invite owners, manage lifecycle.
          </p>
        </div>
        <Button>New tenant</Button>
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
              icon={<Building2 className="h-5 w-5" />}
              title="Can't reach the backend yet"
              description="The tenant list will populate once the ops API is connected."
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
              icon={<Building2 className="h-5 w-5" />}
              title="No tenants yet"
              description="Create the first tenant to start onboarding a business."
            />
          </div>
        ) : (
          <TenantsTable tenants={data} />
        )}
      </div>
    </div>
  );
}

function TenantsTable({ tenants }: { tenants: AdminTenant[] }) {
  return (
    <table className="w-full text-sm">
      <thead className="text-left text-xs font-bold uppercase tracking-wider text-muted-foreground">
        <tr>
          <th className="px-5 py-3">Business</th>
          <th className="px-5 py-3">Owner</th>
          <th className="px-5 py-3">Status</th>
          <th className="px-5 py-3">Created</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-border">
        {tenants.map((tenant) => (
          <tr key={tenant.id}>
            <td className="px-5 py-3 font-semibold">{tenant.name}</td>
            <td className="px-5 py-3 text-muted-foreground">{tenant.ownerEmail}</td>
            <td className="px-5 py-3">
              <Badge tone={STATUS_TONE[tenant.status]}>{tenant.status}</Badge>
            </td>
            <td className="px-5 py-3 text-muted-foreground">
              {new Date(tenant.createdAt).toLocaleDateString()}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
