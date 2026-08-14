"use client";

import { Gauge } from "lucide-react";

import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { adminUsage, type UsageRow } from "@/lib/api";
import { useApi, useAuthToken } from "@/lib/use-api";

const currencyFormatter = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });
const numberFormatter = new Intl.NumberFormat("en-US");

export default function AdminUsagePage() {
  const token = useAuthToken();
  const { data, loading, error, refetch } = useApi(() => adminUsage.list({ token }), [token]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-extrabold tracking-tight">Usage</h1>
        <p className="text-sm text-muted-foreground">
          Per-tenant messages, tokens, and cost — the basis for manual invoicing.
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
              icon={<Gauge className="h-5 w-5" />}
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
              icon={<Gauge className="h-5 w-5" />}
              title="No usage yet"
              description="Usage rolls up here once tenants start sending messages."
            />
          </div>
        ) : (
          <UsageTable rows={data} />
        )}
      </div>
    </div>
  );
}

function UsageTable({ rows }: { rows: UsageRow[] }) {
  return (
    <table className="w-full text-sm">
      <thead className="text-left text-xs font-bold uppercase tracking-wider text-muted-foreground">
        <tr>
          <th className="px-5 py-3">Tenant</th>
          <th className="px-5 py-3">Month</th>
          <th className="px-5 py-3">Messages</th>
          <th className="px-5 py-3">Tokens</th>
          <th className="px-5 py-3">Cost</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-border">
        {rows.map((row) => (
          <tr key={`${row.tenantId}-${row.month}`}>
            <td className="px-5 py-3 font-semibold">{row.tenantName}</td>
            <td className="px-5 py-3 text-muted-foreground">{row.month}</td>
            <td className="px-5 py-3 text-muted-foreground">{numberFormatter.format(row.messages)}</td>
            <td className="px-5 py-3 text-muted-foreground">{numberFormatter.format(row.tokens)}</td>
            <td className="px-5 py-3 font-semibold">{currencyFormatter.format(row.cost)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
